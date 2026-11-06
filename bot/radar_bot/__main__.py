"""Бот «Клиентского радара»: приветствие и кнопка открытия Mini App.

Уведомления о событиях появятся на этапе мониторинга.
"""
import asyncio
import logging
import os
import re

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Message, WebAppInfo

log = logging.getLogger("radar_bot")
_TOKEN_RE = re.compile(r"\d{6,}:[\w-]{30,}")


class _Redact(logging.Filter):
    """Токен бота не должен попасть в лог даже внутри текста ошибки."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if _TOKEN_RE.search(msg):
            record.msg, record.args = _TOKEN_RE.sub("***", msg), None
        if record.exc_info and not record.exc_text:
            record.exc_text = _TOKEN_RE.sub("***", logging.Formatter().formatException(record.exc_info))
        return True

WELCOME = (
    "Привет! Я «Клиентский радар».\n\n"
    "Добавьте ИНН своих клиентов, и я буду каждый день проверять изменения в ЕГРЮЛ, "
    "новые связанные компании, подходящие госпрограммы и финансовые показатели.\n\n"
    "Нажмите кнопку ниже, чтобы открыть кабинет."
)
NO_WEBAPP = "Кабинет пока не опубликован: администратор ещё не указал адрес Mini App."


def app_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📊 Открыть кабинет", web_app=WebAppInfo(url=url))]])


def build_dispatcher(webapp_url: str) -> Dispatcher:
    dp = Dispatcher()

    @dp.message(CommandStart())
    @dp.message(Command("app"))
    async def start(message: Message):
        if webapp_url:
            await message.answer(WELCOME, reply_markup=app_keyboard(webapp_url))
        else:
            await message.answer(NO_WEBAPP)

    @dp.message()
    async def fallback(message: Message):
        if webapp_url:
            await message.answer("Всё управление в кабинете:", reply_markup=app_keyboard(webapp_url))
        else:
            await message.answer(NO_WEBAPP)

    return dp


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for h in logging.getLogger().handlers:
        h.addFilter(_Redact())
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    webapp_url = os.environ.get("WEBAPP_URL", "").strip()
    if webapp_url and not webapp_url.startswith("https://"):
        log.warning("WEBAPP_URL должен начинаться с https:// — Telegram не откроет Mini App по http")
        webapp_url = ""
    bot = Bot(token)
    if webapp_url:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Кабинет", web_app=WebAppInfo(url=webapp_url)))
    await build_dispatcher(webapp_url).start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
