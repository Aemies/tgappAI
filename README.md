# Клиентский радар

Telegram Mini App для клиентских менеджеров: личный портфель ИНН, ежедневный мониторинг изменений через Checko, подбор госпрограмм и финансовый экспресс-анализ. ТЗ: `telegram_miniapp_km_inn_ai_technical_spec_v1_1.md` (v1.1).

Сейчас готов **этап 1 (каркас)**: вход через Telegram с проверкой подписи на сервере и пустой личный кабинет с пятью вкладками.

## Состав

| Папка | Что внутри |
|---|---|
| `backend/` | FastAPI + SQLAlchemy + Alembic. Проверка `initData`, сессия, `/api/v1/me`, `/api/v1/settings`, `/api/v1/overview` |
| `bot/` | Бот на aiogram: `/start`, кнопка «Открыть кабинет», кнопка меню. `presenters.py` — заменяемый слой уведомлений (сейчас текст + кнопки, позже HTML Bubbles) |
| `frontend/` | Mini App на React + Vite, тема берётся из Telegram |
| `docs/` | Результаты этапа 0: что отдаёт Checko API |

## Пилот на Mac (без Docker)

```sh
brew install python node cloudflared     # один раз
./run_mac.sh ~/путь/к/secrets.env
```

Скрипт ставит зависимости, собирает кабинет, создаёт базу SQLite в `data/`, открывает бесплатный HTTPS-туннель Cloudflare и запускает backend и бота. Адрес туннеля меняется при каждом запуске, бот подхватывает его сам. Работает, пока Mac не спит. Не кладите репозиторий в iCloud: `node_modules` и `.venv` будут синхронизироваться.

## Запуск через Docker

```sh
cp secrets.env .env        # или cp .env.example .env и заполнить
docker compose up -d --build
```

Обязательные поля в `.env`: `TELEGRAM_BOT_TOKEN`, `SESSION_SECRET`, `POSTGRES_PASSWORD`. Кабинет откроется на http://localhost:8080, но Telegram открывает Mini App только по **HTTPS**. Поэтому для проверки в Telegram нужен сервер с доменом (этап развёртывания) или временный туннель, адрес которого вписывается в `WEBAPP_URL`.

## Разработка без Docker

```sh
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest              # тесты входа и изоляции пользователей
.venv/bin/alembic upgrade head          # нужна PostgreSQL и DATABASE_URL в .env
.venv/bin/uvicorn app.main:app --reload

cd frontend && npm install && npm run dev   # /api проксируется на localhost:8000
```

## Безопасность

- Личность пользователя подтверждается только подписью `initData` (HMAC-SHA-256 от токена бота). `initDataUnsafe` не используется.
- `user_id` в запросах берётся только из серверного токена сессии (12 часов).
- Секреты лежат в `.env`, он в `.gitignore`. В репозитории только шаблон `.env.example`.
