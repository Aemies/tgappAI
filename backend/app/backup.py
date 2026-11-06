"""Ежедневная резервная копия базы SQLite (режим пилота на Mac).

Копия делается штатным backup API SQLite, поэтому она согласованная даже во время записи.
Хранится backup_keep последних дней. Для PostgreSQL нужен pg_dump по расписанию сервера.
"""
import sqlite3
from datetime import date
from pathlib import Path

from .config import get_settings


def _sqlite_path(url: str) -> Path | None:
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            return Path(url[len(prefix):])
    return None


def maybe_backup(today: date | None = None) -> Path | None:
    st = get_settings()
    src = _sqlite_path(st.database_url)
    if src is None or not src.exists():
        return None
    folder = Path(st.backup_dir) if st.backup_dir else src.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    today = today or date.today()
    dst = folder / f"{src.stem}-{today.isoformat()}.db"
    if dst.exists():
        return None
    tmp = dst.with_suffix(".tmp")
    with sqlite3.connect(src) as s, sqlite3.connect(tmp) as d:
        s.backup(d)
    tmp.replace(dst)
    for old in sorted(folder.glob(f"{src.stem}-*.db"))[:-st.backup_keep]:
        old.unlink()
    return dst


def restore_hint() -> str:
    return "Остановите run_mac.sh и скопируйте нужный файл из data/backups поверх data/radar.db"
