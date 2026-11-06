from datetime import UTC, datetime
from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import User
from ..schemas import SettingsIn, UserOut
from ..session import current_user

router = APIRouter()


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)):
    return user


@router.put("/settings", response_model=UserOut)
async def update_settings(body: SettingsIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if body.timezone is not None:
        if body.timezone not in available_timezones():
            raise HTTPException(422, "Неизвестный часовой пояс")
        user.timezone = body.timezone
    if body.accept_terms and user.accepted_terms_at is None:
        user.accepted_terms_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/overview")
async def overview(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Сводка для вкладки «Обзор». Проверки и события появятся на этапе мониторинга."""
    from .clients import portfolio_count

    return {"clients": await portfolio_count(db, user), "checked_today": 0, "new_events": 0, "errors": 0}
