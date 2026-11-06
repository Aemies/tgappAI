"""Как событие выглядит в чате. Слой заменяемый.

Сейчас: текст + кнопка «Открыть в кабинете» (работает везде).
Позже: HTML Bubble (Telegram 13.2+), когда в Bot API появится официальный метод отправки.
Пузырь не может ходить в сеть, поэтому все данные события передаются внутрь него целиком.
"""
from html import escape
from dataclasses import dataclass, field

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo


@dataclass
class EventCard:
    company: str
    inn: str
    title: str
    date: str
    details: list[str] = field(default_factory=list)
    source_url: str | None = None
    app_path: str = ""  # путь внутри Mini App, например /clients/123


class TextPresenter:
    """Обычное сообщение с кнопками. Работает на всех клиентах."""

    def render(self, card: EventCard, webapp_url: str) -> dict:
        e = escape
        lines = [f"<b>{e(card.company)}</b> · ИНН {e(card.inn)}", f"{e(card.title)} — {e(card.date)}", *[f"• {e(d)}" for d in card.details]]
        buttons = []
        if webapp_url:
            buttons.append([InlineKeyboardButton(text="Открыть в кабинете", web_app=WebAppInfo(url=webapp_url.rstrip("/") + card.app_path))])
        if card.source_url:
            buttons.append([InlineKeyboardButton(text="Источник", url=card.source_url)])
        return {"text": "\n".join(lines), "parse_mode": "HTML", "reply_markup": InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None}


# class HtmlBubblePresenter: появится после выхода метода в Bot API (ожидается 10.4).
# Требования из публикаций: до 32 КБ, без сетевых запросов, данные зашиты в HTML.
