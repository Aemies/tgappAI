import base64
import copy
import json
import os
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select

from app import checko as checko_mod
from app import db as dbmod
from app.config import get_settings
from app.models import MonitorRun, PortfolioItem, RegistryEvent, User
from app.monitoring import diff, normalize, run_for_user
from app.notify import send_pending
from app.worker import tick

from .test_auth import make_init_data

INN = "7707083893"
BASE = {"НаимСокр": "ООО РОМАШКА", "Статус": {"Наим": "Действует"}, "ЮрАдрес": {"АдресРФ": "Москва, ул. Ленина, 1"},
        "Руковод": [{"ФИО": "Иванов И. И.", "НаимДолжн": "ГЕНЕРАЛЬНЫЙ ДИРЕКТОР"}],
        "Учред": {"ФЛ": [{"ФИО": "Иванов И. И.", "Доля": {"Процент": 100.0}}], "РосОрг": [], "ИнОрг": []}, "УстКап": {"Сумма": 10000}}
TL = [{"Дата": "2020-01-01", "Событие": "Регистрация юридического лица"}]


class Fake:
    def __init__(self):
        self.company = copy.deepcopy(BASE)
        self.timeline = list(TL)
        self.fail = False
        self.calls = 0


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(get_settings(), "encryption_master_key", base64.b64encode(os.urandom(32)).decode())
    f = Fake()

    async def fake_get(self, method, **params):
        f.calls += 1
        if f.fail:
            raise checko_mod.CheckoError("Checko недоступен, попробуйте позже")
        meta = {"status": "ok", "today_request_count": f.calls}
        if method == "company":
            return checko_mod.CheckoResult(copy.deepcopy(f.company), meta)
        if method == "timeline":
            return checko_mod.CheckoResult(list(f.timeline), meta)
        raise checko_mod.CheckoError("Не найдено", not_found=True)

    monkeypatch.setattr(checko_mod.CheckoClient, "_get", fake_get)
    return f


async def setup_user(client, uid=1):
    t = (await client.post("/api/v1/auth/telegram", json={"init_data": make_init_data(uid, f"U{uid}")})).json()["token"]
    h = {"Authorization": f"Bearer {t}"}
    await client.post("/api/v1/integrations/checko", json={"api_key": f"key-{uid}-ABCDEFGH"}, headers=h)
    await client.post("/api/v1/clients", json={"inn": INN}, headers=h)
    return h


async def run(uid=1):
    async with dbmod.get_sessionmaker()() as db:
        user = (await db.execute(select(User).where(User.telegram_id == uid))).scalar_one()
        return await run_for_user(db, user, "manual")


async def events(uid=1):
    async with dbmod.get_sessionmaker()() as db:
        return (await db.execute(select(RegistryEvent).join(User, User.id == RegistryEvent.owner_user_id)
                                 .where(User.telegram_id == uid, RegistryEvent.is_baseline.is_(False)))).scalars().all()


def test_diff_lists():
    a, b = normalize("company", BASE), copy.deepcopy(BASE)
    b["Руковод"] = [{"ФИО": "Петров П. П.", "НаимДолжн": "ГЕНЕРАЛЬНЫЙ ДИРЕКТОР"}]
    ch = diff(a, normalize("company", b))
    assert len(ch) == 1 and ch[0]["field"] == "heads" and "Петров" in ch[0]["new"]


async def test_baseline_then_change_once(client, fake):
    h = await setup_user(client)
    r = await run()
    assert r.checked == 1 and r.new_events == 0  # базовый снимок, история не присылается
    assert await events() == []

    fake.company["Руковод"] = [{"ФИО": "Петров П. П.", "НаимДолжн": "ГЕНЕРАЛЬНЫЙ ДИРЕКТОР"}]
    fake.timeline.append({"Дата": "2026-11-05", "Событие": "ООО РОМАШКА становится учредителем (участником) ООО \"ЛУЧ\" /ОГРН 1234567890123/"})
    r = await run()
    evs = await events()
    assert r.new_events == 2 and {e.event_type for e in evs} == {"REGISTRY_CHANGE", "NEW_RELATED_ENTITY"}
    assert any(e.related_ogrn == "1234567890123" for e in evs)

    r = await run()  # повтор без изменений: дубликатов нет
    assert r.new_events == 0 and len(await events()) == 2

    lst = (await client.get("/api/v1/events", headers=h)).json()
    assert len(lst) == 2 and all(not e["read"] for e in lst)
    assert (await client.get("/api/v1/overview", headers=h)).json()["new_events"] == 2
    await client.post("/api/v1/events/read", headers=h)
    assert (await client.get("/api/v1/overview", headers=h)).json()["new_events"] == 0


async def test_failure_creates_no_event(client, fake):
    await setup_user(client)
    await run()
    fake.fail = True
    r = await run()
    assert r.errors == 1 and r.new_events == 0 and await events() == []
    fake.fail = False
    r = await run()  # после восстановления данные те же — событий нет
    assert r.new_events == 0


async def test_quota_respected(client, fake, monkeypatch):
    monkeypatch.setattr(get_settings(), "checko_daily_limit", 8)
    monkeypatch.setattr(get_settings(), "checko_reserve", 0)
    h = await setup_user(client)  # проверка ключа + добавление = 2 запроса
    await client.post("/api/v1/clients", json={"inn": "7736207543"}, headers=h)  # 3
    r = await run()
    assert r.checked + r.skipped_quota == 2 and r.requests_used <= 8


async def test_events_isolated(client, fake):
    hb = await setup_user(client, 2)
    await setup_user(client, 1)
    await run(1)
    fake.company["Статус"] = {"Наим": "В процессе ликвидации"}
    await run(1)
    assert len(await events(1)) == 1
    assert (await client.get("/api/v1/events", headers=hb)).json() == []


async def test_notifications_sent_once(client, fake, monkeypatch):
    monkeypatch.setattr(get_settings(), "webapp_url", "https://app.example.ru")
    sent = []

    def handler(req: httpx.Request):
        sent.append(json.loads(req.content))
        return httpx.Response(200, json={"ok": True, "result": {}})

    await setup_user(client)
    await run()
    fake.company["ЮрАдрес"] = {"АдресРФ": "Москва, ул. Новая, 2"}
    await run()
    async with dbmod.get_sessionmaker()() as db:
        user = (await db.execute(select(User))).scalar_one()
        assert await send_pending(db, user, transport=httpx.MockTransport(handler)) == 1
        assert await send_pending(db, user, transport=httpx.MockTransport(handler)) == 0
    assert len(sent) == 1 and "ул. Новая" in sent[0]["text"] and sent[0]["chat_id"] == 1


async def test_worker_schedule(client, fake, monkeypatch):
    monkeypatch.setattr(get_settings(), "telegram_api_base", "http://127.0.0.1:9")  # уведомления в тесте не уходят
    await setup_user(client)
    early = datetime(2026, 11, 6, 4, 0, tzinfo=UTC)  # 07:00 МСК — рано
    await tick(early)
    async with dbmod.get_sessionmaker()() as db:
        assert (await db.execute(select(MonitorRun))).first() is None
    late = datetime(2026, 11, 6, 7, 0, tzinfo=UTC)  # 10:00 МСК
    await tick(late)
    await tick(late)  # второй раз в тот же день не запускается
    async with dbmod.get_sessionmaker()() as db:
        assert len((await db.execute(select(MonitorRun))).all()) == 1
        assert (await db.execute(select(PortfolioItem))).scalar_one().last_checked_at is not None


async def test_mark_read_body_variants(client, fake):
    h = await setup_user(client)
    assert (await client.post("/api/v1/events/read", content="null", headers={**h, "Content-Type": "application/json"})).status_code == 200
    assert (await client.post("/api/v1/events/read", json=[1, 2], headers=h)).status_code == 200
