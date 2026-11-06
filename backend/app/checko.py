"""Клиент Checko API (https://api.checko.ru/v2). Ключ передаётся явно: у каждого пользователя свой."""
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import get_settings

# ИНН для проверки ключа: ПАО Сбербанк. Проверка тратит 1 запрос из дневного лимита.
_TEST_INN = "7707083893"


class CheckoError(RuntimeError):
    def __init__(self, message: str, *, auth: bool = False, not_found: bool = False):
        super().__init__(message)
        self.auth = auth
        self.not_found = not_found


@dataclass
class CheckoResult:
    data: Any
    meta: dict = field(default_factory=dict)


class CheckoClient:
    def __init__(self, api_key: str, transport: httpx.AsyncBaseTransport | None = None):
        self._key = api_key
        self._transport = transport

    async def _get(self, method: str, **params) -> CheckoResult:
        async with httpx.AsyncClient(base_url=get_settings().checko_base_url, timeout=20, transport=self._transport) as client:
            try:
                r = await client.get(f"/{method}", params={"key": self._key, **params})
            except httpx.HTTPError:
                raise CheckoError("Checko недоступен, попробуйте позже")
        try:
            body = r.json()
        except ValueError:
            raise CheckoError(f"Checko вернул некорректный ответ ({r.status_code})")
        meta = body.get("meta") or {}
        if meta.get("status") != "ok":
            msg = meta.get("message") or "Ошибка Checko"
            low = msg.lower()
            raise CheckoError(msg, auth="ключ" in low or "key" in low, not_found="не найден" in low)
        data = body.get("data")
        if data in (None, {}, []) and "не найден" in (meta.get("message") or "").lower():
            raise CheckoError(meta["message"], not_found=True)
        return CheckoResult(data=data, meta=meta)

    async def company(self, inn: str) -> CheckoResult:
        return await self._get("company", inn=inn)

    async def entrepreneur(self, inn: str) -> CheckoResult:
        return await self._get("entrepreneur", inn=inn)

    async def timeline(self, inn: str) -> CheckoResult:
        return await self._get("timeline", inn=inn)

    async def test(self) -> CheckoResult:
        return await self.company(_TEST_INN)


def summarize(subject_type: str, data: dict) -> dict:
    """Нормализованные поля карточки из ответа Checko."""
    def name(v):
        return v.get("Наим") if isinstance(v, dict) else v

    if subject_type == "company":
        title = data.get("НаимСокр") or data.get("НаимПолн")
        head = (data.get("Руковод") or [{}])[0]
        return {
            "name": title,
            "full_name": data.get("НаимПолн"),
            "ogrn": data.get("ОГРН"),
            "status": name(data.get("Статус")),
            "region": name(data.get("Регион")),
            "okved": " ".join(filter(None, [(data.get("ОКВЭД") or {}).get("Код"), (data.get("ОКВЭД") or {}).get("Наим")])) or None,
            "registered": data.get("ДатаРег"),
            "address": (data.get("ЮрАдрес") or {}).get("АдресРФ") if isinstance(data.get("ЮрАдрес"), dict) else data.get("ЮрАдрес"),
            "head": " — ".join(filter(None, [head.get("ФИО"), head.get("НаимДолжн")])) or None,
            "sme_category": (data.get("РМСП") or {}).get("Кат"),
            "employees": data.get("СЧР"),
            "source_date": data.get("ДатаВып"),
        }
    return {
        "name": "ИП " + (data.get("ФИО") or "") if data.get("ФИО") else None,
        "full_name": data.get("ФИО"),
        "ogrn": data.get("ОГРНИП") or data.get("ОГРН"),
        "status": name(data.get("Статус")),
        "region": name(data.get("Регион")),
        "okved": " ".join(filter(None, [(data.get("ОКВЭД") or {}).get("Код"), (data.get("ОКВЭД") or {}).get("Наим")])) or None,
        "registered": data.get("ДатаРег") or data.get("ДатаОГРНИП"),
        "address": None,
        "head": None,
        "sme_category": (data.get("РМСП") or {}).get("Кат"),
        "employees": data.get("СЧР"),
        "source_date": data.get("ДатаВып"),
    }
