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
    if body.notifications_enabled is not None:
        user.notifications_enabled = body.notifications_enabled
    if body.accept_terms and user.accepted_terms_at is None:
        user.accepted_terms_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/overview")
async def overview(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Сводка для вкладки «Обзор». Проверки и события появятся на этапе мониторинга."""
    from sqlalchemy import select

    from ..models import PortfolioItem
    from ..monitoring import local_date, unread_count
    from .clients import portfolio_count

    items = (await db.execute(select(PortfolioItem.last_checked_at, PortfolioItem.last_check_error).where(PortfolioItem.owner_user_id == user.id))).all()
    today = local_date(user)
    checked = sum(1 for t, _ in items if t and local_date(user, t) == today)
    errors = sum(1 for t, e in items if e)
    return {"clients": await portfolio_count(db, user), "checked_today": checked, "new_events": await unread_count(db, user), "errors": errors}
