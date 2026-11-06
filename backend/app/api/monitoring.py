import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db, get_sessionmaker
from ..models import CompanyProfile, MonitorRun, PortfolioItem, RegistryEvent, User
from ..monitoring import last_run, run_for_user
from ..notify import send_pending
from ..session import current_user
from .integrations import get_credential

router = APIRouter()
_running: set[int] = set()


class RunOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    started_at: datetime
    finished_at: datetime | None
    trigger: str
    checked: int
    errors: int
    skipped_quota: int
    new_events: int
    requests_used: int


class EventOut(BaseModel):
    id: int
    client_id: int
    inn: str
    company: str | None
    event_type: str
    title: str
    effective_date: str | None
    detected_at: datetime
    read: bool


async def _run_bg(user_id: int):
    try:
        async with get_sessionmaker()() as db:
            user = await db.get(User, user_id)
            await run_for_user(db, user, "manual")
            await send_pending(db, user)
    finally:
        _running.discard(user_id)


@router.post("/monitoring/run")
async def run_now(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if await get_credential(db, user) is None:
        raise HTTPException(409, "Сначала подключите свой ключ Checko в настройках")
    if user.id in _running:
        return {"started": False, "running": True}
    _running.add(user.id)
    asyncio.create_task(_run_bg(user.id))
    return {"started": True, "running": True}


@router.get("/monitoring/status")
async def status(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    run = await last_run(db, user)
    return {"running": user.id in _running or bool(run and run.finished_at is None and (datetime.now(UTC) - run.started_at.replace(tzinfo=run.started_at.tzinfo or UTC)).total_seconds() < 600),
            "last_run": RunOut.model_validate(run) if run else None}


@router.get("/events", response_model=list[EventOut])
async def list_events(unread: bool = False, client_id: int | None = None, limit: int = 100,
                      user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    q = (select(RegistryEvent, PortfolioItem, CompanyProfile).join(PortfolioItem, PortfolioItem.id == RegistryEvent.portfolio_item_id)
         .outerjoin(CompanyProfile, CompanyProfile.portfolio_item_id == PortfolioItem.id)
         .where(RegistryEvent.owner_user_id == user.id))
    # события базового снимка — это история до подключения, в ленту их не выводим
    q = q.where(RegistryEvent.is_baseline.is_(False))
    if unread:
        q = q.where(RegistryEvent.read_at.is_(None))
    if client_id:
        q = q.where(RegistryEvent.portfolio_item_id == client_id)
    rows = (await db.execute(q.order_by(RegistryEvent.detected_at.desc(), RegistryEvent.id.desc()).limit(min(limit, 500)))).all()
    return [EventOut(id=e.id, client_id=i.id, inn=i.inn, company=(p.summary or {}).get("name") if p else None, event_type=e.event_type,
                     title=e.title, effective_date=e.effective_date, detected_at=e.detected_at, read=e.read_at is not None) for e, i, p in rows]


@router.post("/events/read")
async def mark_read(ids: list[int] | None = None, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    q = RegistryEvent.__table__.update().where(RegistryEvent.owner_user_id == user.id, RegistryEvent.read_at.is_(None))
    if ids:
        q = q.where(RegistryEvent.id.in_(ids))
    await db.execute(q.values(read_at=datetime.now(UTC)))
    await db.commit()
    return {"ok": True}
