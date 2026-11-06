import base64
import os

import pytest

from app import checko as checko_mod
from app.config import get_settings
from app.inn import validate

from .test_auth import make_init_data

SBER, YANDEX = "7707083893", "7736207543"
VALID_IP = "500100732259"
COMPANIES = {
    SBER: {"НаимСокр": "ПАО СБЕРБАНК", "ОГРН": "1027700132195", "Статус": {"Наим": "Действует"}, "Регион": {"Наим": "Москва"},
           "ОКВЭД": {"Код": "64.19", "Наим": "Денежное посредничество прочее"}, "Руковод": [{"ФИО": "Греф Г. О.", "НаимДолжн": "ПРЕЗИДЕНТ"}]},
    YANDEX: {"НаимСокр": "ООО \"ЯНДЕКС\"", "Статус": {"Наим": "Действует"}},
}


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setattr(get_settings(), "encryption_master_key", base64.b64encode(os.urandom(32)).decode())
    calls = []

    async def fake_get(self, method, **params):
        calls.append((self._key, method, params.get("inn")))
        if self._key == "badkey12345":
            raise checko_mod.CheckoError("Неверный ключ API", auth=True)
        if method == "company" and params["inn"] in COMPANIES:
            return checko_mod.CheckoResult(COMPANIES[params["inn"]], {"status": "ok", "today_request_count": len(calls)})
        raise checko_mod.CheckoError("Не найдено ни одного лица", not_found=True)

    monkeypatch.setattr(checko_mod.CheckoClient, "_get", fake_get)
    return calls


async def login(client, uid):
    t = (await client.post("/api/v1/auth/telegram", json={"init_data": make_init_data(uid, f"U{uid}")})).json()["token"]
    return {"Authorization": f"Bearer {t}"}


def test_inn_checksum():
    assert validate(SBER) == "company"
    assert validate(VALID_IP) == "ip"
    assert validate("7707083894") is None
    assert validate("123") is None


async def test_key_lifecycle(client, setup):
    h = await login(client, 1)
    assert (await client.get("/api/v1/integrations/checko", headers=h)).json()["connected"] is False
    r = (await client.post("/api/v1/integrations/checko", json={"api_key": "goodkey-1234ABCD"}, headers=h)).json()
    assert r["status"] == "ok" and r["key_mask"] == "••••ABCD" and "goodkey" not in str(r)
    r = (await client.post("/api/v1/integrations/checko", json={"api_key": "badkey12345"}, headers=h)).json()
    assert r["status"] == "invalid" and r["last_error"]
    assert (await client.delete("/api/v1/integrations/checko", headers=h)).json()["connected"] is False


async def test_key_stored_encrypted(client):
    from sqlalchemy import select

    from app import db as dbmod
    from app.models import ProviderCredential

    h = await login(client, 1)
    await client.post("/api/v1/integrations/checko", json={"api_key": "goodkey-1234ABCD"}, headers=h)
    async with dbmod.get_sessionmaker()() as s:
        cred = (await s.execute(select(ProviderCredential))).scalar_one()
    assert "goodkey" not in cred.encrypted_secret


async def test_add_requires_key_and_valid_inn(client):
    h = await login(client, 1)
    assert (await client.post("/api/v1/clients", json={"inn": "7707083894"}, headers=h)).status_code == 422
    assert (await client.post("/api/v1/clients", json={"inn": SBER}, headers=h)).status_code == 409


async def test_add_and_card(client, setup):
    h = await login(client, 1)
    await client.post("/api/v1/integrations/checko", json={"api_key": "goodkey-1234ABCD"}, headers=h)
    r = await client.post("/api/v1/clients", json={"inn": "7707 083 893"}, headers=h)
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["name"] == "ПАО СБЕРБАНК" and card["summary"]["okved"].startswith("64.19") and card["fetch_status"] == "ok"
    assert (await client.post("/api/v1/clients", json={"inn": SBER}, headers=h)).status_code == 409
    assert (await client.get("/api/v1/overview", headers=h)).json()["clients"] == 1
    # не найденный ИП сохраняется со статусом not_found
    r = (await client.post("/api/v1/clients", json={"inn": VALID_IP}, headers=h)).json()
    assert r["fetch_status"] == "not_found"


async def test_import(client):
    h = await login(client, 1)
    r = (await client.post("/api/v1/clients/import", json={"text": f"inn\n{SBER}\n{YANDEX};{SBER}\n7707083894"}, headers=h)).json()
    assert r == {"added": 2, "duplicates": 1, "invalid": ["7707083894"]}
    r = (await client.post("/api/v1/clients/import", json={"text": f"{SBER} {YANDEX}"}, headers=h)).json()
    assert r["added"] == 0 and r["duplicates"] == 2
    items = (await client.get("/api/v1/clients", headers=h)).json()
    assert {i["inn"] for i in items} == {SBER, YANDEX} and all(i["fetch_status"] == "pending" for i in items)


async def test_portfolio_isolation(client, setup):
    a, b = await login(client, 1), await login(client, 2)
    for h, key in ((a, "goodkey-AAAA1111"), (b, "goodkey-BBBB2222")):
        await client.post("/api/v1/integrations/checko", json={"api_key": key}, headers=h)
    ca = (await client.post("/api/v1/clients", json={"inn": SBER}, headers=a)).json()
    cb = (await client.post("/api/v1/clients", json={"inn": SBER}, headers=b)).json()  # тот же ИНН у второго пользователя
    assert ca["id"] != cb["id"]
    # каждый запрос к Checko шёл с ключом владельца
    assert [k for k, m, i in setup if m == "company" and i == SBER][-2:] == ["goodkey-AAAA1111", "goodkey-BBBB2222"]
    # B не видит и не может трогать клиента A
    assert len((await client.get("/api/v1/clients", headers=b)).json()) == 1
    assert (await client.get(f"/api/v1/clients/{ca['id']}", headers=b)).status_code == 404
    assert (await client.post(f"/api/v1/clients/{ca['id']}/refresh", headers=b)).status_code == 404
    assert (await client.delete(f"/api/v1/clients/{ca['id']}", headers=b)).status_code == 404
    assert (await client.get(f"/api/v1/clients/{ca['id']}", headers=a)).status_code == 200
    # удаление ключа B не трогает ключ A
    await client.delete("/api/v1/integrations/checko", headers=b)
    assert (await client.get("/api/v1/integrations/checko", headers=a)).json()["connected"] is True
