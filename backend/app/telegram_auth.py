"""Проверка подписи Telegram.WebApp.initData (официальный алгоритм HMAC-SHA-256).

https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


class InitDataError(ValueError):
    pass


@dataclass(frozen=True)
class TelegramUser:
    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None


def _secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def sign(fields: dict[str, str], bot_token: str) -> str:
    """Подпись набора полей так же, как это делает Telegram (нужно для тестов)."""
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    return hmac.new(_secret_key(bot_token), check_string.encode(), hashlib.sha256).hexdigest()


def validate_init_data(init_data: str, bot_token: str, max_age: int, now: float | None = None) -> TelegramUser:
    if not init_data:
        raise InitDataError("empty initData")
    fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    received_hash = fields.pop("hash", None)
    if not received_hash:
        raise InitDataError("no hash")
    expected = sign(fields, bot_token)
    if not hmac.compare_digest(expected, received_hash):
        raise InitDataError("bad signature")
    try:
        auth_date = int(fields["auth_date"])
    except (KeyError, ValueError):
        raise InitDataError("no auth_date")
    now = time.time() if now is None else now
    if now - auth_date > max_age or auth_date - now > 60:
        raise InitDataError("initData expired")
    try:
        raw = json.loads(fields["user"])
        return TelegramUser(
            id=int(raw["id"]),
            first_name=raw.get("first_name"),
            last_name=raw.get("last_name"),
            username=raw.get("username"),
            language_code=raw.get("language_code"),
        )
    except (KeyError, ValueError, TypeError):
        raise InitDataError("no user")
