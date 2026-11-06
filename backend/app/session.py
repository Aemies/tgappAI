"""Короткоживущая сессия Mini App: подписанный токен в заголовке Authorization.

user_id берётся только из токена, выданного сервером после проверки initData,
и никогда из тела запроса.
"""
import time

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .db import get_db
from .models import User

_bearer = HTTPBearer(auto_error=False)


def issue_token(user_id: int, settings: Settings) -> str:
    now = int(time.time())
    return jwt.encode({"sub": str(user_id), "iat": now, "exp": now + settings.session_ttl}, settings.session_secret, algorithm="HS256")


async def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нет сессии")
    try:
        payload = jwt.decode(creds.credentials, settings.session_secret, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия недействительна")
    user = await db.get(User, user_id)
    if user is None or user.status != "active":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь не найден")
    return user
