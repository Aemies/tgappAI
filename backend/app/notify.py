"""Уведомления о событиях в Telegram. Сейчас текст + кнопка, позже HTML Bubbles (см. bot/radar_bot/presenters.py)."""
from collections import defaultdict
from datetime import UTC, datetime
from html import escape

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .models import CompanyProfile, PortfolioItem, RegistryEvent, User

MAX_ATTEMPTS = 5
MAX_PER_MESSAGE = 10


def render(item: PortfolioItem, name: str | None, events: list[RegistryEvent]) -> str:
    lines = [f"🔔 <b>{escape(name or 'ИНН ' + item.inn)}</b> · ИНН {item.inn}"]
    for ev in events[:MAX_PER_MESSAGE]:
        date = f" ({ev.effective_date})" if ev.effective_date else ""
        lines.append(f"• {escape(ev.title)}{date}")
    if len(events) > MAX_PER_MESSAGE:
        lines.append(f"…и ещё {len(events) - MAX_PER_MESSAGE} в кабинете")
    lines.append("<i>Источник: Checko</i>")
    return "\n".join(lines)


async def send_pending(db: AsyncSession, user: User, transport: httpx.AsyncBaseTransport | None = None) -> int:
    st = get_settings()
    if not user.notifications_enabled:
        return 0
    rows = (await db.execute(select(RegistryEvent, PortfolioItem).join(PortfolioItem, PortfolioItem.id == RegistryEvent.portfolio_item_id)
                             .where(RegistryEvent.owner_user_id == user.id, RegistryEvent.notified_at.is_(None),
                                    RegistryEvent.notify_attempts < MAX_ATTEMPTS).order_by(RegistryEvent.id))).all()
    by_item: dict[int, tuple[PortfolioItem, list[RegistryEvent]]] = {}
    groups = defaultdict(list)
    for ev, item in rows:
        by_item[item.id] = (item, groups[item.id])
        groups[item.id].append(ev)
    sent = 0
    async with httpx.AsyncClient(base_url=f"{st.telegram_api_base}/bot{st.telegram_bot_token}", timeout=20, transport=transport) as tg:
        for item, evs in by_item.values():
            profile = (await db.execute(select(CompanyProfile).where(CompanyProfile.portfolio_item_id == item.id))).scalar_one_or_none()
            name = (profile.summary or {}).get("name") if profile else None
            payload = {"chat_id": user.telegram_id, "text": render(item, name, evs), "parse_mode": "HTML", "disable_web_page_preview": True}
            if st.webapp_url.startswith("https://"):
                payload["reply_markup"] = {"inline_keyboard": [[{"text": "Открыть в кабинете", "web_app": {"url": st.webapp_url}}]]}
            ok = False
            try:
                r = await tg.post("/sendMessage", json=payload)
                ok = r.status_code == 200 and r.json().get("ok")
            except (httpx.HTTPError, ValueError):
                ok = False
            now = datetime.now(UTC)
            for ev in evs:
                ev.notify_attempts += 1
                if ok:
                    ev.notified_at = now
            sent += int(bool(ok))
    await db.commit()
    return sent
