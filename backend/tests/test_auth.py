import json
import time
from urllib.parse import urlencode

import pytest

from app.telegram_auth import InitDataError, sign, validate_init_data

TOKEN = "123456:TEST-TOKEN"


def make_init_data(user_id=42, first_name="Анна", auth_date=None, token=TOKEN, tamper=False):
    fields = {
        "auth_date": str(int(auth_date or time.time())),
        "query_id": "AAH",
        "user": json.dumps({"id": user_id, "first_name": first_name, "username": f"u{user_id}"}, ensure_ascii=False),
    }
    fields["hash"] = sign(fields, token)
    if tamper:
        fields["user"] = fields["user"].replace(str(user_id), str(user_id + 1))
    return urlencode(fields)


def test_valid_init_data():
    u = validate_init_data(make_init_data(), TOKEN, 3600)
    assert u.id == 42 and u.first_name == "Анна"


@pytest.mark.parametrize("data", [
    make_init_data(tamper=True),
    make_init_data(token="999:OTHER"),
    make_init_data(auth_date=time.time() - 7200),
    "",
    "user=%7B%7D",
])
def test_invalid_init_data(data):
    with pytest.raises(InitDataError):
        validate_init_data(data, TOKEN, 3600)


async def test_login_and_me(client):
    r = await client.post("/api/v1/auth/telegram", json={"init_data": make_init_data()})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    me = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["first_name"] == "Анна"


async def test_rejects_forged_login(client):
    r = await client.post("/api/v1/auth/telegram", json={"init_data": make_init_data(tamper=True)})
    assert r.status_code == 401


async def test_me_requires_session(client):
    assert (await client.get("/api/v1/me")).status_code == 401
    assert (await client.get("/api/v1/me", headers={"Authorization": "Bearer junk"})).status_code == 401


async def test_users_are_isolated(client):
    ta = (await client.post("/api/v1/auth/telegram", json={"init_data": make_init_data(1, "A")})).json()["token"]
    tb = (await client.post("/api/v1/auth/telegram", json={"init_data": make_init_data(2, "B")})).json()["token"]
    a = (await client.get("/api/v1/me", headers={"Authorization": f"Bearer {ta}"})).json()
    b = (await client.get("/api/v1/me", headers={"Authorization": f"Bearer {tb}"})).json()
    assert a["id"] != b["id"] and a["first_name"] == "A" and b["first_name"] == "B"


async def test_settings(client):
    t = (await client.post("/api/v1/auth/telegram", json={"init_data": make_init_data()})).json()["token"]
    h = {"Authorization": f"Bearer {t}"}
    r = await client.put("/api/v1/settings", json={"timezone": "Asia/Yekaterinburg", "accept_terms": True}, headers=h)
    assert r.status_code == 200 and r.json()["timezone"] == "Asia/Yekaterinburg" and r.json()["accepted_terms_at"]
    assert (await client.put("/api/v1/settings", json={"timezone": "Mars/Base"}, headers=h)).status_code == 422
