"""Ежедневный мониторинг: снимок карточки + хронология Checko → подтверждённые события.

Правила (ТЗ, раздел 6):
- первая проверка клиента только фиксирует базовый снимок, событий не создаёт;
- событие создаётся только из успешного ответа источника, сбой не порождает ложных изменений;
- ключ события детерминирован, повторная проверка не дублирует события.
"""
import hashlib
import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .checko import CheckoClient, CheckoError, summarize
from .config import get_settings
from .models import CompanyProfile, MonitorRun, MonitorSnapshot, PortfolioItem, ProviderCredential, RegistryEvent, User

FIELDS = {
    "name": "Наименование",
    "status": "Статус",
    "address": "Юридический адрес",
    "heads": "Руководитель",
    "founders": "Учредители",
    "okved": "Основной ОКВЭД",
    "capital": "Уставный капитал",
    "region": "Регион",
    "sme_category": "Категория МСП",
    "bankruptcy": "Сообщения о банкротстве (ЕФРСБ)",
    "bad_supplier": "Реестр недобросовестных поставщиков",
}


def _name(v):
    return v.get("Наим") if isinstance(v, dict) else v


def normalize(subject_type: str, data: dict) -> dict:
    s = summarize(subject_type, data)
    heads = sorted(f"{h.get('ФИО')} ({h.get('НаимДолжн') or h.get('ВидДолжн') or 'руководитель'})" for h in data.get("Руковод") or [] if h.get("ФИО"))
    founders = []
    uch = data.get("Учред") or {}
    if isinstance(uch, dict):
        for f in uch.get("ФЛ") or []:
            share = (f.get("Доля") or {}).get("Процент")
            founders.append(f"{f.get('ФИО')}" + (f" — {share:g}%" if isinstance(share, (int, float)) else ""))
        for f in (uch.get("РосОрг") or []) + (uch.get("ИнОрг") or []):
            share = (f.get("Доля") or {}).get("Процент")
            founders.append(f"{f.get('НаимСокр') or f.get('НаимПолн')}" + (f" — {share:g}%" if isinstance(share, (int, float)) else ""))
    cap = (data.get("УстКап") or {}).get("Сумма") if isinstance(data.get("УстКап"), dict) else None
    return {
        "name": s.get("name"),
        "status": s.get("status"),
        "address": s.get("address"),
        "heads": heads,
        "founders": sorted(founders),
        "okved": s.get("okved"),
        "capital": cap,
        "region": s.get("region"),
        "sme_category": s.get("sme_category"),
        "bankruptcy": len(data.get("ЕФРСБ") or []),
        "bad_supplier": bool(data.get("НедобПост")),
    }


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _fmt(v) -> str:
    if v in (None, "", []):
        return "—"
    if isinstance(v, list):
        return "; ".join(map(str, v))
    if isinstance(v, bool):
        return "да" if v else "нет"
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, int) and abs(v) >= 1000:
        return f"{v:,}".replace(",", " ")
    return str(v)


def diff(old: dict, new: dict) -> list[dict]:
    changes = []
    for field, label in FIELDS.items():
        a, b = old.get(field), new.get(field)
        if a == b:
            continue
        if isinstance(a, list) or isinstance(b, list):
            a, b = a or [], b or []
            added, removed = [x for x in b if x not in a], [x for x in a if x not in b]
            changes.append({"field": field, "label": label, "old": _fmt(a), "new": _fmt(b), "added": added, "removed": removed})
        else:
            changes.append({"field": field, "label": label, "old": _fmt(a), "new": _fmt(b)})
    return changes


def change_title(c: dict) -> str:
    if c.get("added") and not c.get("removed"):
        return f"{c['label']}: добавлено — {_fmt(c['added'])}"
    if c.get("removed") and not c.get("added"):
        return f"{c['label']}: исключено — {_fmt(c['removed'])}"
    return f"{c['label']}: {c['old']} → {c['new']}"


def timeline_type(text: str) -> str:
    t = text.lower()
    if "становится учредителем" in t or "становится руководителем" in t or "создано" in t:
        return "NEW_RELATED_ENTITY"
    return "REGISTRY_CHANGE"


def _ogrn(text: str) -> str | None:
    import re

    m = re.search(r"ОГРН\s*(\d{13,15})", text)
    return m.group(1) if m else None


class QuotaExhausted(Exception):
    pass


class Budget:
    """Следит, чтобы проверка не съела весь дневной лимит Checko."""

    def __init__(self, used_today: int | None):
        st = get_settings()
        self.limit = st.checko_daily_limit - st.checko_reserve
        self.used_today = used_today or 0
        self.used_now = 0

    def take(self, n: int):
        if self.used_today + n > self.limit:
            raise QuotaExhausted
        self.used_today += n
        self.used_now += n

    def sync(self, meta: dict):
        c = meta.get("today_request_count")
        if isinstance(c, int):
            self.used_today = max(self.used_today, c)


async def _add_event(db: AsyncSession, item: PortfolioItem, **kw) -> RegistryEvent | None:
    exists = (await db.execute(select(RegistryEvent.id).where(RegistryEvent.portfolio_item_id == item.id,
                                                              RegistryEvent.event_key == kw["event_key"]))).first()
    if exists:
        return None
    ev = RegistryEvent(owner_user_id=item.owner_user_id, portfolio_item_id=item.id, **kw)
    db.add(ev)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return None
    return ev


async def check_item(db: AsyncSession, item: PortfolioItem, client: CheckoClient, budget: Budget) -> list[RegistryEvent]:
    need = 2 if item.subject_type == "company" else 1
    budget.take(need)
    now = datetime.now(UTC)
    try:
        res = await (client.company(item.inn) if item.subject_type == "company" else client.entrepreneur(item.inn))
        budget.sync(res.meta)
        data = res.data if isinstance(res.data, dict) else {}
        if not data:
            raise CheckoError("Не найдено в реестре", not_found=True)
        timeline = []
        if item.subject_type == "company":
            tl = await client.timeline(item.inn)
            budget.sync(tl.meta)
            timeline = [e for e in (tl.data or []) if isinstance(e, dict) and e.get("Дата") and e.get("Событие")]
    except CheckoError as e:
        # сбой источника — не событие; фиксируем ошибку и ничего не сравниваем
        item.last_checked_at, item.last_check_error = now, str(e)[:255]
        await db.commit()
        return []

    norm = normalize(item.subject_type, data)
    tl_last = max((e["Дата"] for e in timeline), default=None)
    prev = (await db.execute(select(MonitorSnapshot).where(MonitorSnapshot.portfolio_item_id == item.id)
                             .order_by(MonitorSnapshot.fetched_at.desc(), MonitorSnapshot.id.desc()).limit(1))).scalar_one_or_none()
    events: list[RegistryEvent] = []
    if prev is not None:
        for c in diff(prev.normalized_payload, norm):
            ev = await _add_event(db, item, event_key=_hash(["snap", c["field"], c["old"], c["new"]])[:64], event_type="REGISTRY_CHANGE",
                                  title=change_title(c)[:500], details=c, effective_date=None, source="snapshot")
            if ev:
                events.append(ev)
        since = prev.timeline_last_date
        for e in timeline:
            if since and e["Дата"] < since:
                continue
            ev = await _add_event(db, item, event_key=_hash(["tl", e["Дата"], e["Событие"]])[:64], event_type=timeline_type(e["Событие"]),
                                  title=e["Событие"][:500], details={"text": e["Событие"]}, related_ogrn=_ogrn(e["Событие"]),
                                  effective_date=e["Дата"], source="timeline")
            if ev:
                events.append(ev)
    else:
        # базовый снимок: запоминаем уже существующие события хронологии, чтобы не присылать историю
        for e in timeline:
            await _add_event(db, item, event_key=_hash(["tl", e["Дата"], e["Событие"]])[:64], event_type=timeline_type(e["Событие"]),
                             title=e["Событие"][:500], details={"text": e["Событие"]}, related_ogrn=_ogrn(e["Событие"]),
                             effective_date=e["Дата"], source="timeline", is_baseline=True, read_at=now, notified_at=now)

    db.add(MonitorSnapshot(owner_user_id=item.owner_user_id, portfolio_item_id=item.id, snapshot_hash=_hash(norm), normalized_payload=norm,
                           timeline_last_date=tl_last or (prev.timeline_last_date if prev else None), is_baseline=prev is None, fetched_at=now))
    # заодно обновляем карточку клиента свежими данными
    profile = (await db.execute(select(CompanyProfile).where(CompanyProfile.portfolio_item_id == item.id))).scalar_one_or_none()
    summary = summarize(item.subject_type, data)
    if profile is None:
        db.add(CompanyProfile(owner_user_id=item.owner_user_id, portfolio_item_id=item.id, summary=summary, payload=data, fetched_at=now))
    else:
        profile.summary, profile.payload, profile.fetched_at = summary, data, now
    item.fetch_status, item.fetch_error = "ok", None
    item.last_checked_at, item.last_check_error = now, None
    await db.commit()
    return events


def local_date(user: User, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    try:
        tz = ZoneInfo(user.timezone)
    except Exception:
        tz = ZoneInfo("Europe/Moscow")
    return now.astimezone(tz).date().isoformat()


async def run_for_user(db: AsyncSession, user: User, trigger: str) -> MonitorRun:
    from . import crypto

    cred = (await db.execute(select(ProviderCredential).where(ProviderCredential.owner_user_id == user.id,
                                                              ProviderCredential.provider_code == "checko"))).scalar_one_or_none()
    run = MonitorRun(owner_user_id=user.id, local_date=local_date(user), trigger=trigger)
    db.add(run)
    await db.commit()
    if cred is None:
        run.finished_at = datetime.now(UTC)
        await db.commit()
        return run
    client = CheckoClient(crypto.decrypt(cred.encrypted_secret, f"user:{user.id}:checko"))
    # счётчик запросов сбрасывается в полночь по Москве; если последняя проверка ключа была в другой день — считаем с нуля
    used = cred.requests_today if cred.last_tested_at and local_date(user, cred.last_tested_at) == run.local_date else 0
    budget = Budget(used)
    items = (await db.execute(select(PortfolioItem).where(PortfolioItem.owner_user_id == user.id, PortfolioItem.monitoring_enabled.is_(True))
                              .order_by(PortfolioItem.last_checked_at.is_(None).desc(), PortfolioItem.last_checked_at, PortfolioItem.id))).scalars().all()
    for item in items:
        try:
            evs = await check_item(db, item, client, budget)
        except QuotaExhausted:
            run.skipped_quota += 1
            continue
        run.checked += 1
        run.new_events += len(evs)
        if item.last_check_error:
            run.errors += 1
    run.requests_used = budget.used_now
    run.finished_at = datetime.now(UTC)
    cred.requests_today, cred.last_tested_at = budget.used_today, run.finished_at
    await db.commit()
    return run


async def last_run(db: AsyncSession, user: User) -> MonitorRun | None:
    return (await db.execute(select(MonitorRun).where(MonitorRun.owner_user_id == user.id).order_by(MonitorRun.id.desc()).limit(1))).scalar_one_or_none()


async def unread_count(db: AsyncSession, user: User) -> int:
    return (await db.execute(select(func.count()).select_from(RegistryEvent).where(RegistryEvent.owner_user_id == user.id,
                                                                                   RegistryEvent.read_at.is_(None), RegistryEvent.is_baseline.is_(False)))).scalar_one()
