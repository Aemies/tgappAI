from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crypto
from ..checko import CheckoClient, CheckoError
from ..db import get_db
from ..models import ProviderCredential, User
from ..session import current_user

router = APIRouter()
PROVIDER = "checko"


class KeyIn(BaseModel):
    api_key: str = Field(min_length=8, max_length=256)


class CredentialOut(BaseModel):
    connected: bool
    key_mask: str | None = None
    status: str | None = None
    last_tested_at: datetime | None = None
    last_error: str | None = None
    requests_today: int | None = None


def _aad(user_id: int) -> str:
    return f"user:{user_id}:{PROVIDER}"


def _out(c: ProviderCredential | None) -> CredentialOut:
    if c is None:
        return CredentialOut(connected=False)
    return CredentialOut(connected=True, key_mask=f"••••{c.key_suffix}", status=c.status, last_tested_at=c.last_tested_at,
                         last_error=c.last_error, requests_today=c.requests_today)


async def get_credential(db: AsyncSession, user: User) -> ProviderCredential | None:
    return (await db.execute(select(ProviderCredential).where(ProviderCredential.owner_user_id == user.id,
                                                              ProviderCredential.provider_code == PROVIDER))).scalar_one_or_none()


async def checko_for(db: AsyncSession, user: User) -> CheckoClient:
    cred = await get_credential(db, user)
    if cred is None:
        raise HTTPException(409, "Сначала подключите свой ключ Checko в настройках")
    return CheckoClient(crypto.decrypt(cred.encrypted_secret, _aad(user.id)))


async def _test(db: AsyncSession, user: User, cred: ProviderCredential) -> None:
    client = CheckoClient(crypto.decrypt(cred.encrypted_secret, _aad(user.id)))
    cred.last_tested_at = datetime.now(UTC)
    try:
        res = await client.test()
        cred.status, cred.last_error = "ok", None
        cred.requests_today = res.meta.get("today_request_count")
    except CheckoError as e:
        cred.status = "invalid" if e.auth else "error"
        cred.last_error = str(e)[:255]
    await db.commit()


@router.get("/integrations/checko", response_model=CredentialOut)
async def get_checko(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return _out(await get_credential(db, user))


@router.post("/integrations/checko", response_model=CredentialOut)
async def save_checko(body: KeyIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    key = body.api_key.strip()
    try:
        secret = crypto.encrypt(key, _aad(user.id))
    except crypto.CryptoError:
        raise HTTPException(500, "Сервер не настроен для хранения ключей")
    cred = await get_credential(db, user)
    if cred is None:
        cred = ProviderCredential(owner_user_id=user.id, provider_code=PROVIDER, encrypted_secret=secret, key_suffix=key[-4:])
        db.add(cred)
    else:
        cred.encrypted_secret, cred.key_suffix = secret, key[-4:]
    cred.status, cred.last_error = "untested", None
    await db.commit()
    await _test(db, user, cred)
    return _out(cred)


@router.post("/integrations/checko/test", response_model=CredentialOut)
async def test_checko(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    cred = await get_credential(db, user)
    if cred is None:
        raise HTTPException(404, "Ключ не подключён")
    await _test(db, user, cred)
    return _out(cred)


@router.delete("/integrations/checko", response_model=CredentialOut)
async def delete_checko(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    cred = await get_credential(db, user)
    if cred is not None:
        await db.delete(cred)
        await db.commit()
    return _out(None)
