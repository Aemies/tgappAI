"""Фоновый планировщик: раз в минуту смотрит, кому пора делать ежедневную проверку, и досылает уведомления.

Запуск: python -m app.worker
"""
import asyncio
import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .config import get_settings
from .db import get_sessionmaker
from .models import MonitorRun, ProviderCredential, User
from .monitoring import local_date, run_for_user
from .notify import send_pending
from .security import setup_logging
from .backup import maybe_backup

log = logging.getLogger("radar.worker")


def is_due(user: User, now: datetime, hour: int) -> bool:
    try:
        tz = ZoneInfo(user.timezone)
    except Exception:
        tz = ZoneInfo("Europe/Moscow")
    return now.astimezone(tz).hour >= hour


async def _tick_user(user_id: int, now: datetime, hour: int) -> None:
    async with get_sessionmaker()() as db:
        user = await db.get(User, user_id)
        if user is None:
            return
        today = local_date(user, now)
        done = (await db.execute(select(MonitorRun.id).where(MonitorRun.owner_user_id == user.id, MonitorRun.local_date == today,
                                                             MonitorRun.trigger == "schedule"))).first()
        if not done and is_due(user, now, hour):
            run = await run_for_user(db, user, "schedule")
            log.info("user=%s checked=%s events=%s errors=%s quota_skipped=%s", user.id, run.checked, run.new_events, run.errors, run.skipped_quota)
        await send_pending(db, user)


async def tick(now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    hour = get_settings().monitor_hour
    async with get_sessionmaker()() as db:
        ids = (await db.execute(select(User.id).join(ProviderCredential, ProviderCredential.owner_user_id == User.id)
                                .where(User.status == "active", ProviderCredential.provider_code == "checko"))).scalars().all()
    for uid in ids:
        # у каждого пользователя своя сессия БД: сбой у одного (ключ, сеть, данные) не останавливает остальных
        try:
            await _tick_user(uid, now, hour)
        except Exception:
            log.exception("Сбой проверки user=%s", uid)


async def main() -> None:
    setup_logging()
    log.info("Планировщик мониторинга запущен, проверка в %02d:00 по поясу пользователя", get_settings().monitor_hour)
    while True:
        try:
            await tick()
        except Exception:
            log.exception("Сбой цикла мониторинга")
        try:
            made = maybe_backup()
            if made:
                log.info("Резервная копия базы: %s", made)
        except Exception:
            log.exception("Не удалось сделать резервную копию")
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
