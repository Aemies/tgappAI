from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..db import get_db
from ..models import User
from ..schemas import AuthRequest, AuthResponse, UserOut
from ..session import issue_token
from ..telegram_auth import InitDataError, validate_init_data

router = APIRouter()


@router.post("/auth/telegram", response_model=AuthResponse)
async def auth_telegram(body: AuthRequest, db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)):
    try:
        tg = validate_init_data(body.init_data, settings.telegram_bot_token, settings.init_data_max_age)
    except InitDataError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Не удалось подтвердить вход через Telegram")

    user = (await db.execute(select(User).where(User.telegram_id == tg.id))).scalar_one_or_none()
    if user is None:
        user = User(telegram_id=tg.id, timezone=settings.default_timezone)
        db.add(user)
    user.first_name = tg.first_name
    user.username = tg.username
    user.language_code = tg.language_code
    user.last_seen_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(user)
    return AuthResponse(token=issue_token(user.id, settings), user=UserOut.model_validate(user))
