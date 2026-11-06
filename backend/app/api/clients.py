from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import inn as innlib
from ..checko import CheckoError, summarize
from ..db import get_db
from ..models import CompanyProfile, PortfolioItem, User
from ..session import current_user
from .integrations import checko_for

router = APIRouter()
MAX_IMPORT = 500


class AddIn(BaseModel):
    inn: str = Field(max_length=32)
    label: str | None = Field(default=None, max_length=255)


class ImportIn(BaseModel):
    text: str = Field(max_length=100_000)


class ClientOut(BaseModel):
    id: int
    inn: str
    subject_type: str
    label: str | None
    monitoring_enabled: bool
    fetch_status: str
    fetch_error: str | None
    name: str | None = None
    status: str | None = None
    region: str | None = None
    created_at: datetime


class ClientCard(ClientOut):
    summary: dict | None = None
    fetched_at: datetime | None = None


def _out(item: PortfolioItem, profile: CompanyProfile | None, card: bool = False):
    s = profile.summary if profile else {}
    base = dict(id=item.id, inn=item.inn, subject_type=item.subject_type, label=item.label, monitoring_enabled=item.monitoring_enabled,
                fetch_status=item.fetch_status, fetch_error=item.fetch_error, name=s.get("name"), status=s.get("status"),
                region=s.get("region"), created_at=item.created_at)
    if card:
        return ClientCard(**base, summary=s or None, fetched_at=profile.fetched_at if profile else None)
    return ClientOut(**base)


async def _own_item(db: AsyncSession, user: User, item_id: int) -> PortfolioItem:
    item = (await db.execute(select(PortfolioItem).where(PortfolioItem.id == item_id, PortfolioItem.owner_user_id == user.id))).scalar_one_or_none()
    if item is None:  # чужой и несуществующий объект неотличимы: защита от IDOR
        raise HTTPException(404, "Клиент не найден")
    return item


async def _profile(db: AsyncSession, item: PortfolioItem) -> CompanyProfile | None:
    return (await db.execute(select(CompanyProfile).where(CompanyProfile.portfolio_item_id == item.id))).scalar_one_or_none()


async def _fetch(db: AsyncSession, user: User, item: PortfolioItem) -> CompanyProfile | None:
    client = await checko_for(db, user)
    try:
        res = await (client.company(item.inn) if item.subject_type == "company" else client.entrepreneur(item.inn))
        data = res.data if isinstance(res.data, dict) else {}
        if not data:
            raise CheckoError("Не найдено в ЕГРЮЛ/ЕГРИП", not_found=True)
    except CheckoError as e:
        item.fetch_status = "not_found" if e.not_found else "error"
        item.fetch_error = str(e)[:255]
        await db.commit()
        return await _profile(db, item)
    profile = await _profile(db, item)
    summary = summarize(item.subject_type, data)
    if profile is None:
        profile = CompanyProfile(owner_user_id=user.id, portfolio_item_id=item.id, summary=summary, payload=data)
        db.add(profile)
    else:
        profile.summary, profile.payload, profile.fetched_at = summary, data, datetime.now(UTC)
    item.fetch_status, item.fetch_error = "ok", None
    await db.commit()
    return profile


def _parse(raw: str) -> tuple[str, str]:
    inn = innlib.normalize(raw)
    kind = innlib.validate(inn)
    if kind is None:
        raise HTTPException(422, "Некорректный ИНН: проверьте цифры (10 для организации, 12 для ИП)")
    return inn, kind


@router.get("/clients", response_model=list[ClientOut])
async def list_clients(q: str | None = None, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(PortfolioItem, CompanyProfile).outerjoin(CompanyProfile, CompanyProfile.portfolio_item_id == PortfolioItem.id)
                             .where(PortfolioItem.owner_user_id == user.id).order_by(PortfolioItem.created_at.desc(), PortfolioItem.id.desc()))).all()
    out = [_out(i, p) for i, p in rows]
    if q:
        ql = q.lower()
        out = [c for c in out if ql in c.inn or ql in (c.name or "").lower() or ql in (c.label or "").lower()]
    return out


@router.post("/clients", response_model=ClientCard)
async def add_client(body: AddIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    inn, kind = _parse(body.inn)
    await checko_for(db, user)  # без ключа не добавляем: карточку нечем проверить
    exists = (await db.execute(select(PortfolioItem).where(PortfolioItem.owner_user_id == user.id, PortfolioItem.inn == inn))).scalar_one_or_none()
    if exists:
        raise HTTPException(409, "Этот ИНН уже в вашем портфеле")
    item = PortfolioItem(owner_user_id=user.id, inn=inn, subject_type=kind, label=body.label)
    db.add(item)
    await db.commit()
    profile = await _fetch(db, user, item)
    return _out(item, profile, card=True)


@router.post("/clients/import")
async def import_clients(body: ImportIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Массовая загрузка: ИНН через запятую, пробел, перенос строки или из CSV. Карточки подгружаются позже по кнопке."""
    import re

    tokens = re.findall(r"(?<!\d)\d{9,13}(?!\d)", body.text)
    seen, valid, invalid = set(), [], []
    for t in tokens:
        inn = innlib.normalize(t)
        if inn in seen:
            continue
        seen.add(inn)
        kind = innlib.validate(inn)
        (valid if kind else invalid).append((inn, kind))
    if len(valid) > MAX_IMPORT:
        raise HTTPException(422, f"За один раз можно загрузить до {MAX_IMPORT} ИНН")
    existing = set((await db.execute(select(PortfolioItem.inn).where(PortfolioItem.owner_user_id == user.id))).scalars())
    added = [inn for inn, _ in valid if inn not in existing]
    for inn, kind in valid:
        if inn not in existing:
            db.add(PortfolioItem(owner_user_id=user.id, inn=inn, subject_type=kind))
    await db.commit()
    return {"added": len(added), "duplicates": len(valid) - len(added), "invalid": [i for i, _ in invalid]}


@router.get("/clients/{item_id}", response_model=ClientCard)
async def get_client(item_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    item = await _own_item(db, user, item_id)
    return _out(item, await _profile(db, item), card=True)


@router.post("/clients/{item_id}/refresh", response_model=ClientCard)
async def refresh_client(item_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    item = await _own_item(db, user, item_id)
    profile = await _fetch(db, user, item)
    return _out(item, profile, card=True)


@router.delete("/clients/{item_id}")
async def delete_client(item_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    item = await _own_item(db, user, item_id)
    profile = await _profile(db, item)
    if profile:
        await db.delete(profile)
    await db.delete(item)
    await db.commit()
    return {"ok": True}


async def portfolio_count(db: AsyncSession, user: User) -> int:
    return (await db.execute(select(func.count()).select_from(PortfolioItem).where(PortfolioItem.owner_user_id == user.id))).scalar_one()
