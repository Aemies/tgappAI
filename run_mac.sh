#!/bin/bash
# Пилот «Клиентского радара» на Mac: всё в одном процессе, без Docker и PostgreSQL.
#   ./run_mac.sh [путь к secrets.env]
# Что делает: ставит зависимости, собирает кабинет, поднимает базу SQLite,
# открывает бесплатный HTTPS-туннель Cloudflare, запускает backend и бота.
# Остановить: Ctrl+C. Работает, пока Mac не спит.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"
SECRETS="${1:-$ROOT/.env}"
DATA="$ROOT/data"; mkdir -p "$DATA"
LOG="$DATA/logs"; mkdir -p "$LOG"

[ -f "$SECRETS" ] || { echo "Нет файла с секретами: $SECRETS"; exit 1; }
set -a; . "$SECRETS"; set +a
: "${TELEGRAM_BOT_TOKEN:?Заполните TELEGRAM_BOT_TOKEN}" "${SESSION_SECRET:?Заполните SESSION_SECRET}"
export DATABASE_URL="sqlite+aiosqlite:///$DATA/radar.db"
export STATIC_DIR="$ROOT/frontend/dist"

need() { command -v "$1" >/dev/null || { echo "Не найден $1. Установите: brew install $2"; exit 1; }; }
need python3 python; need npm node; need cloudflared cloudflared

if [ ! -d .venv ]; then python3 -m venv .venv; fi
.venv/bin/pip install -q -r backend/requirements.txt -r bot/requirements.txt

if [ ! -f frontend/dist/index.html ] || [ frontend/src -nt frontend/dist/index.html ]; then
  (cd frontend && npm install --no-audit --no-fund --silent && npm run build --silent)
fi

(cd backend && ../.venv/bin/alembic upgrade head)

PIDS=()
cleanup() { echo; echo "Останавливаю…"; kill ${PIDS[@]+"${PIDS[@]}"} 2>/dev/null || true; }
trap cleanup EXIT INT TERM

cloudflared tunnel --no-autoupdate --protocol http2 --url http://127.0.0.1:8000 >"$LOG/tunnel.log" 2>&1 &
PIDS+=($!)
URL=""
for _ in $(seq 1 30); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG/tunnel.log" | head -1 || true)
  [ -n "$URL" ] && break; sleep 1
done
[ -n "$URL" ] || { echo "Туннель не поднялся, см. $LOG/tunnel.log"; exit 1; }
export WEBAPP_URL="$URL"

# ждём, пока туннель реально подключится, иначе бот раздаст неработающую ссылку
for _ in $(seq 1 60); do
  grep -q "Registered tunnel connection" "$LOG/tunnel.log" && break; sleep 1
done
grep -q "Registered tunnel connection" "$LOG/tunnel.log" || { echo "Туннель не подключился за минуту, см. $LOG/tunnel.log"; exit 1; }

(cd backend && exec ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000) >"$LOG/backend.log" 2>&1 &
PIDS+=($!)
(cd backend && exec ../.venv/bin/python -m app.worker) >"$LOG/worker.log" 2>&1 &
PIDS+=($!)
(cd bot && exec ../.venv/bin/python -m radar_bot) >"$LOG/bot.log" 2>&1 &
PIDS+=($!)

echo "Готово. Кабинет: $URL"
echo "Отправьте боту /start и откройте кабинет кнопкой из НОВОГО сообщения: старые кнопки ведут на прошлый адрес. Логи: $LOG"
wait
