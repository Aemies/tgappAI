"""Предрелизные проверки: приватность всех адресов API, защита, удаление данных, устойчивость worker, резервные копии."""
import logging
import re
from datetime import UTC, date, datetime

import pytest

from app import worker
from app.db import get_sessionmaker
from app.main import app
from app.models import AIConnection, PortfolioItem, RegistryEvent, User
from app.security import RedactFilter, redact

from .test_finance_ai import FakeProviders, add_client_with_finance, finances, providers  # noqa: F401
from .test_portfolio import SBER, login, setup  # noqa: F401


async def seed_user_a(client):
    a = await login(client, 1)
    cid = await add_client_with_finance(client, a)
    conn = (await client.post("/api/v1/ai/connections", json={"provider": "openai", "api_key": "sk-userA-1111", "name": "ИИ пользователя A"},
                              headers=a)).json()
    async with get_sessionmaker()() as db:
        uid = (await db.get(PortfolioItem, cid)).owner_user_id
        ev = RegistryEvent(owner_user_id=uid, portfolio_item_id=cid, event_key="k1", event_type="REGISTRY_CHANGE", title="Секретное событие A",
                           details={}, source="snapshot")
        db.add(ev)
        await db.commit()
        eid = ev.id
    return a, cid, conn["id"], eid


async def test_every_id_route_is_owner_only(client, finances, providers):
    """Перебираем ВСЕ адреса API с идентификатором в пути: чужой пользователь получает только 404."""
    a, cid, conn_id, eid = await seed_user_a(client)
    b = await login(client, 2)
    ids = {"item_id": cid, "conn_id": conn_id, "client_id": cid, "event_id": eid}
    bodies = {"put": {"name": "взлом"}, "post": {}}
    checked = 0
    for path, ops in app.openapi()["paths"].items():
        if "{" not in path:
            continue
        url = re.sub(r"\{(\w+)\}", lambda m: str(ids[m.group(1)]), path)
        for method in ops:
            kw = {"json": bodies[method]} if method in bodies else {}
            r = await client.request(method.upper(), url, headers=b, **kw)
            assert r.status_code == 404, (method, path, r.status_code, r.text)
            assert SBER not in r.text and "СБЕРБАНК" not in r.text.upper()
            checked += 1
    assert checked >= 9  # все адреса с id на 2026-11-06; новый адрес попадёт в проверку сам
    # Списки B пусты, чтение чужих событий по id ничего не меняет
    for url in ("/api/v1/clients", "/api/v1/events", f"/api/v1/events?client_id={cid}", "/api/v1/ai/connections"):
        assert (await client.get(url, headers=b)).json() == []
    await client.post("/api/v1/events/read", json=[eid], headers=b)
    assert (await client.get("/api/v1/events?unread=true", headers=a)).json()[0]["title"] == "Секретное событие A"
    assert (await client.post("/api/v1/programs/check", json={"client_id": cid}, headers=b)).status_code == 404
    # Данные A не тронуты
    assert (await client.get(f"/api/v1/clients/{cid}", headers=a)).status_code == 200
    assert (await client.get("/api/v1/ai/connections", headers=a)).json()[0]["name"] == "ИИ пользователя A"


async def test_no_secret_in_any_response(client, finances, providers):
    a, cid, conn_id, _ = await seed_user_a(client)
    texts = []
    for url in ("/api/v1/integrations/checko", "/api/v1/ai/connections", f"/api/v1/clients/{cid}", f"/api/v1/clients/{cid}/finance", "/api/v1/me"):
        texts.append((await client.get(url, headers=a)).text)
    blob = "".join(texts)
    assert "goodkey-1234" not in blob and "sk-userA" not in blob and "encrypted" not in blob


def test_logs_are_redacted(caplog):
    samples = [
        "HTTP Request: GET https://api.checko.ru/v2/company?key=SuperSecretKey123&inn=7707083893",
        "POST https://api.telegram.org/bot123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw/sendMessage",
        "Authorization: Bearer sk-proj-abcdefghijklmnop",
    ]
    for s in samples:
        out = redact(s)
        assert "SuperSecretKey123" not in out and "AAHdqTcv" not in out and "abcdefghijk" not in out
    assert "inn=7707083893" in redact(samples[0])
    assert logging.getLogger("httpx").level >= logging.WARNING
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "url %s", (samples[0],), None)
    RedactFilter().filter(rec)
    assert "SuperSecretKey123" not in rec.getMessage()


async def test_rate_limit_and_body_limit(client):
    h = await login(client, 1)
    codes = [(await client.post("/api/v1/integrations/checko", json={"api_key": "goodkey-1234ABCD"}, headers=h)).status_code for _ in range(32)]
    assert codes[:30] == [200] * 30 and codes[-1] == 429
    big = "1" * 1_100_000
    r = await client.post("/api/v1/clients/import", content=f'{{"text": "{big}"}}', headers={**h, "Content-Type": "application/json"})
    assert r.status_code == 413


async def test_headers_no_cors_no_docs(client):
    r = await client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff" and "frame-ancestors" in r.headers["content-security-policy"]
    pre = await client.options("/api/v1/me", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in pre.headers
    assert (await client.get("/api/docs")).status_code == 404


async def test_delete_my_data(client, finances, providers):
    a, cid, conn_id, _ = await seed_user_a(client)
    b = await login(client, 2)
    await client.post("/api/v1/integrations/checko", json={"api_key": "goodkey-1234ABCD"}, headers=b)
    cid_b = (await client.post("/api/v1/clients", json={"inn": SBER}, headers=b)).json()["id"]
    assert (await client.delete("/api/v1/me", headers=a)).json()["deleted"]
    assert (await client.get("/api/v1/me", headers=a)).status_code == 401  # старая сессия больше не работает
    async with get_sessionmaker()() as db:
        from sqlalchemy import func, select

        from app import models
        for m in (models.PortfolioItem, models.CompanyProfile, models.FinanceReport, models.AIConnection, models.AIUsageEvent,
                  models.RegistryEvent, models.ProviderCredential):
            owners = (await db.execute(select(m.owner_user_id, func.count()).group_by(m.owner_user_id))).all()
            assert all(o != 1 for o, _ in owners), m.__tablename__
        assert (await db.execute(select(func.count()).select_from(User))).scalar_one() == 1
    # данные B на месте, A при повторном входе начинает с нуля
    assert (await client.get(f"/api/v1/clients/{cid_b}", headers=b)).status_code == 200
    a2 = await login(client, 1)
    me = (await client.get("/api/v1/me", headers=a2)).json()
    assert me["accepted_terms_at"] is None and (await client.get("/api/v1/clients", headers=a2)).json() == []


async def test_worker_survives_one_user_failure(client, monkeypatch):
    for uid in (1, 2):
        h = await login(client, uid)
        await client.post("/api/v1/integrations/checko", json={"api_key": "goodkey-1234ABCD"}, headers=h)
    async with get_sessionmaker()() as db:
        from sqlalchemy import select
        ids = (await db.execute(select(User.id).order_by(User.id))).scalars().all()
    done = []

    async def fake_run(db, user, trigger):
        if user.id == ids[0]:
            raise RuntimeError("Checko упал у первого")
        done.append(user.id)

        class R:
            checked = new_events = errors = skipped_quota = 0
        return R()

    async def no_send(db, user, transport=None):
        return 0

    monkeypatch.setattr(worker, "run_for_user", fake_run)
    monkeypatch.setattr(worker, "send_pending", no_send)
    await worker.tick(datetime(2026, 11, 6, 12, 0, tzinfo=UTC))
    assert done == [ids[1]]


def test_backup_rotation(tmp_path, monkeypatch):
    import sqlite3

    from app import backup
    from app.config import get_settings
    dbfile = tmp_path / "radar.db"
    with sqlite3.connect(dbfile) as c:
        c.execute("create table t(x)")
        c.execute("insert into t values (42)")
    st = get_settings()
    monkeypatch.setattr(st, "database_url", f"sqlite+aiosqlite:///{dbfile}")
    monkeypatch.setattr(st, "backup_dir", "")
    monkeypatch.setattr(st, "backup_keep", 3)
    for d in range(1, 6):
        assert backup.maybe_backup(date(2026, 11, d)) is not None
    assert backup.maybe_backup(date(2026, 11, 5)) is None  # второй раз за день не копирует
    files = sorted(p.name for p in (tmp_path / "backups").glob("*.db"))
    assert files == ["radar-2026-11-03.db", "radar-2026-11-04.db", "radar-2026-11-05.db"]
    with sqlite3.connect(tmp_path / "backups" / files[-1]) as c:
        assert c.execute("select x from t").fetchone() == (42,)


@pytest.mark.parametrize("model", [AIConnection])
def test_models_have_owner(model):
    assert hasattr(model, "owner_user_id")
