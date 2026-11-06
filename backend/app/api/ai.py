"""«Мой ИИ»: личные подключения пользователя к ИИ-провайдерам (ТЗ 22.6)."""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import ai, crypto
from ..db import get_db
from ..models import AIConnection, AIUsageEvent, User
from ..session import current_user

router = APIRouter()
MAX_CONNECTIONS = 10
# Шлюз подменяется в тестах
gateway = ai.Gateway()


def _aad(user_id: int, conn_id_hint: str) -> str:
    return f"user:{user_id}:ai:{conn_id_hint}"


class ConnIn(BaseModel):
    provider: str
    api_key: str = Field(min_length=8, max_length=4096)
    name: str | None = Field(default=None, max_length=100)
    model_id: str | None = Field(default=None, max_length=200)
    folder_id: str | None = Field(default=None, max_length=64)
    scope: str | None = Field(default=None, pattern="^GIGACHAT_API_(PERS|B2B|CORP)$")


class ConnPatch(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    model_id: str | None = Field(default=None, max_length=200)
    is_default: bool | None = None
    data_level: int | None = Field(default=None, ge=1, le=2)
    monthly_request_limit: int | None = Field(default=None, ge=1, le=10000)
    max_tokens: int | None = Field(default=None, ge=200, le=8000)


async def used_this_month(db: AsyncSession, conn: AIConnection) -> int:
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    q = select(func.count()).select_from(AIUsageEvent).where(AIUsageEvent.connection_id == conn.id, AIUsageEvent.created_at >= start,
                                                              AIUsageEvent.purpose != "test")
    return (await db.execute(q)).scalar_one()


async def _out(db: AsyncSession, c: AIConnection) -> dict:
    p = ai.PROVIDERS.get(c.provider_code)
    return {"id": c.id, "provider": c.provider_code, "provider_title": p.title if p else c.provider_code, "name": c.name, "model_id": c.model_id,
            "auth_type": c.auth_type, "masked_secret": f"••••{c.key_suffix}", "status": c.status, "last_error": c.last_error,
            "last_tested_at": c.last_tested_at, "is_default": c.is_default, "data_level": c.data_level,
            "monthly_request_limit": c.monthly_request_limit, "max_tokens": c.max_tokens, "used_this_month": await used_this_month(db, c),
            "models": (c.settings or {}).get("models", []), "folder_id": (c.settings or {}).get("folder_id")}


async def _own(db: AsyncSession, user: User, conn_id: int) -> AIConnection:
    c = await db.get(AIConnection, conn_id)
    if c is None or c.owner_user_id != user.id:
        raise HTTPException(404, "Подключение не найдено")
    return c


def decrypted(user: User, c: AIConnection) -> ai.Conn:
    s = c.settings or {}
    return ai.Conn(provider=c.provider_code, api_key=crypto.decrypt(c.encrypted_secret, _aad(user.id, s["aad"])), model=c.model_id,
                   folder_id=s.get("folder_id"), scope=s.get("scope") or "GIGACHAT_API_PERS", id=c.id)


async def _test(db: AsyncSession, user: User, c: AIConnection) -> None:
    c.last_tested_at = datetime.now(UTC)
    try:
        models = await gateway.list_models(decrypted(user, c))
        s = dict(c.settings or {})
        s["models"] = models
        c.settings = s
        if not c.model_id or (models and ai.PROVIDERS[c.provider_code].has_model_list and c.model_id not in models):
            if c.model_id and c.model_id not in models:
                c.status, c.last_error = "no_model", f"Модель {c.model_id} недоступна по этому ключу — выберите другую"[:255]
                await db.commit()
                return
            c.model_id = ai.pick_default(c.provider_code, models)
        c.status, c.last_error = ("ok", None) if c.model_id else ("no_model", "Провайдер не вернул ни одной модели")
    except ai.AIError as e:
        c.status, c.last_error = e.code, str(e)[:255]
    db.add(AIUsageEvent(owner_user_id=user.id, connection_id=c.id, provider_code=c.provider_code, model_id=c.model_id, purpose="test",
                        prompt_version="-", status=c.status))
    await db.commit()


async def default_connection(db: AsyncSession, user: User, conn_id: int | None = None) -> AIConnection | None:
    if conn_id:
        return await _own(db, user, conn_id)
    rows = (await db.execute(select(AIConnection).where(AIConnection.owner_user_id == user.id)
                             .order_by(AIConnection.is_default.desc(), AIConnection.id))).scalars().all()
    return rows[0] if rows else None


@router.get("/ai/providers")
async def providers(user: User = Depends(current_user)):
    return [{"code": p.code, "title": p.title, "auth_methods": ["api_key"], "oauth_supported": p.oauth_supported, "oauth_enabled": False,
             "has_model_list": p.has_model_list, "fixed_models": list(p.fixed_models), "needs_folder": p.needs_folder,
             "key_hint": p.key_hint, "docs": p.docs, "notes": p.notes} for p in ai.PROVIDERS.values()]


@router.get("/ai/connections")
async def list_connections(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AIConnection).where(AIConnection.owner_user_id == user.id).order_by(AIConnection.id))).scalars().all()
    return [await _out(db, c) for c in rows]


@router.post("/ai/connections")
async def create_connection(body: ConnIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    p = ai.PROVIDERS.get(body.provider)
    if p is None:
        raise HTTPException(422, "Провайдер не поддерживается")
    if p.needs_folder and not (body.folder_id or "").strip():
        raise HTTPException(422, "Укажите ID каталога Yandex Cloud")
    count = (await db.execute(select(func.count()).select_from(AIConnection).where(AIConnection.owner_user_id == user.id))).scalar_one()
    if count >= MAX_CONNECTIONS:
        raise HTTPException(409, f"Не больше {MAX_CONNECTIONS} подключений")
    key = body.api_key.strip()
    import secrets as _s

    hint = _s.token_hex(8)
    try:
        enc = crypto.encrypt(key, _aad(user.id, hint))
    except crypto.CryptoError:
        raise HTTPException(500, "Сервер не настроен для хранения ключей")
    settings = {"aad": hint}
    if body.folder_id:
        settings["folder_id"] = body.folder_id.strip()
    if body.scope:
        settings["scope"] = body.scope
    c = AIConnection(owner_user_id=user.id, provider_code=p.code, name=(body.name or "").strip() or f"Мой {p.title.split(' ')[0]}",
                     model_id=(body.model_id or "").strip() or None, encrypted_secret=enc, key_suffix=key[-4:], settings=settings,
                     is_default=count == 0)
    db.add(c)
    await db.commit()
    await _test(db, user, c)
    return await _out(db, c)


@router.post("/ai/connections/{conn_id}/test")
async def test_connection(conn_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    c = await _own(db, user, conn_id)
    await _test(db, user, c)
    return await _out(db, c)


@router.put("/ai/connections/{conn_id}")
async def update_connection(conn_id: int, body: ConnPatch, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    c = await _own(db, user, conn_id)
    if body.name is not None and body.name.strip():
        c.name = body.name.strip()
    if body.model_id is not None:
        models = (c.settings or {}).get("models") or []
        if models and body.model_id not in models:
            raise HTTPException(422, "Такой модели нет в списке доступных по ключу")
        c.model_id = body.model_id
        if c.status == "no_model":
            c.status, c.last_error = "ok", None
    for f in ("data_level", "monthly_request_limit", "max_tokens"):
        v = getattr(body, f)
        if v is not None:
            setattr(c, f, v)
    if body.is_default:
        for other in (await db.execute(select(AIConnection).where(AIConnection.owner_user_id == user.id))).scalars():
            other.is_default = other.id == c.id
    await db.commit()
    return await _out(db, c)


@router.delete("/ai/connections/{conn_id}")
async def delete_connection(conn_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    c = await _own(db, user, conn_id)
    was_default = c.is_default
    await db.delete(c)
    await db.commit()
    if was_default:
        nxt = await default_connection(db, user)
        if nxt:
            nxt.is_default = True
            await db.commit()
    return {"ok": True}
