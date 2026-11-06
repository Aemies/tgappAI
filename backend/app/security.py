"""Защита на уровне приложения (ТЗ 12.9): маскирование секретов в логах, лимиты частоты и размера, заголовки.

Ключи пользователей уходят к Checko в строке запроса (?key=…), токен бота — в пути (/bot<токен>/).
httpx пишет каждый запрос в лог на уровне INFO, поэтому его логгеры поднимаются до WARNING,
а все сообщения проходят через фильтр, который вырезает секреты.
"""
import logging
import re
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .models import User
from .session import current_user

_SECRET_PATTERNS = [
    (re.compile(r"([?&](?:key|api_key|apikey|token)=)[^&\s\"']+", re.I), r"\1***"),
    (re.compile(r"(/bot)\d+:[\w-]+"), r"\1***"),
    (re.compile(r"(Bearer\s+)[\w.\-~+/=]+", re.I), r"\1***"),
    (re.compile(r"(Api-Key\s+)[\w.\-]+", re.I), r"\1***"),
    (re.compile(r"(Basic\s+)[\w+/=]+", re.I), r"\1***"),
    (re.compile(r"\bsk-[\w-]{8,}"), "sk-***"),
]


def redact(text: str) -> str:
    for pat, repl in _SECRET_PATTERNS:
        text = pat.sub(repl, text)
    return text


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        if record.exc_info and record.exc_text is None:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def setup_logging(level: int = logging.INFO) -> None:
    """Вызывать в каждом процессе (backend, worker, bot) до первого запроса."""
    if not logging.getLogger().handlers:
        logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    f = RedactFilter()
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access", "radar.worker", "aiogram"):
        lg = logging.getLogger(name)
        if not any(isinstance(x, RedactFilter) for x in lg.filters):
            lg.addFilter(f)
        for h in lg.handlers:
            if not any(isinstance(x, RedactFilter) for x in h.filters):
                h.addFilter(f)


class RateLimiter:
    """Скользящее окно в памяти процесса. Для одного backend-процесса пилота этого достаточно."""

    def __init__(self):
        self._hits: dict[tuple[str, str], deque] = defaultdict(deque)

    def hit(self, bucket: str, who: str, limit: int, window: float) -> bool:
        now = time.monotonic()
        q = self._hits[(bucket, who)]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


limiter = RateLimiter()

# Лимиты на пользователя: защищают его же дневную квоту Checko и бюджет ИИ от зацикленного клиента
LIMITS = {"checko": (30, 60), "ai": (10, 60), "import": (10, 60), "auth": (30, 60)}


def limit(bucket: str):
    n, window = LIMITS[bucket]

    async def dep(user: User = Depends(current_user)) -> User:
        if not limiter.hit(bucket, str(user.id), n, window):
            raise HTTPException(429, "Слишком много запросов подряд, подождите минуту")
        return user

    return dep


def limit_ip(bucket: str):
    n, window = LIMITS[bucket]

    async def dep(request: Request) -> None:
        ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")
        if not limiter.hit(bucket, ip, n, window):
            raise HTTPException(429, "Слишком много попыток входа, подождите минуту")

    return dep


MAX_BODY = 1_000_000  # 1 МБ: импорт 500 ИНН занимает ~7 КБ

CSP = ("default-src 'self'; script-src 'self' https://telegram.org; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'self' https://web.telegram.org https://*.telegram.org; base-uri 'none'; form-action 'self'")


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > MAX_BODY:
            return JSONResponse({"detail": "Слишком большой запрос"}, status_code=413)
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Content-Security-Policy", CSP)
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.url.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp


class BodyLimitMiddleware:
    """Ограничение размера тела и без Content-Length: туннель Cloudflare пересылает запросы частями (chunked).

    При превышении сразу отвечаем 413, а приложению сообщаем, что клиент отключился: FastAPI иначе
    превратил бы ошибку чтения тела в 400.
    """

    def __init__(self, app, max_body: int = MAX_BODY):
        self.app, self.max_body = app, max_body

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        state = {"total": 0, "rejected": False}

        async def limited():
            if state["rejected"]:
                return {"type": "http.disconnect"}
            msg = await receive()
            if msg["type"] == "http.request":
                state["total"] += len(msg.get("body", b""))
                if state["total"] > self.max_body:
                    state["rejected"] = True
                    await JSONResponse({"detail": "Слишком большой запрос"}, status_code=413)(scope, receive, send)
                    return {"type": "http.disconnect"}
            return msg

        async def guarded_send(msg):
            if not state["rejected"]:
                await send(msg)

        await self.app(scope, limited, guarded_send)
