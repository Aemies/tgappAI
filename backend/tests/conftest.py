import os

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:TEST-TOKEN")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-0123456789abcdef")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app import db as dbmod  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
async def client():
    from app.security import limiter

    limiter.reset()
    sm = dbmod.get_sessionmaker()
    engine = sm.kw["bind"]
    async with engine.begin() as conn:
        await conn.run_sync(dbmod.Base.metadata.drop_all)
        await conn.run_sync(dbmod.Base.metadata.create_all)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
