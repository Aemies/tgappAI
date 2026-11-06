import json

import httpx
import pytest

from app import ai
from app import checko as checko_mod
from app.api import ai as ai_api
from app.finance import analyze

from .test_portfolio import COMPANIES, SBER, login, setup  # noqa: F401  (фикстура с подменой Checko)

# Отчётность в рублях по кодам строк, как отдаёт Checko /finances
FIN = {
    "2023": {"2110": 100_000_000, "2120": -70_000_000, "2200": 20_000_000, "2300": 12_000_000, "2320": 1_000_000, "2330": -3_000_000,
             "2400": 9_000_000, "1200": 50_000_000, "1250": 5_000_000, "1300": 40_000_000, "1410": 20_000_000, "1500": 30_000_000,
             "1510": 10_000_000, "1600": 100_000_000},
    "2024": {"2110": 120_000_000, "2120": 85_000_000, "2200": 22_000_000, "2300": 15_000_000, "2320": 1_000_000, "2330": 4_000_000,
             "2400": 11_000_000, "1200": 60_000_000, "1250": 6_000_000, "1300": 45_000_000, "1410": 25_000_000, "1500": 40_000_000,
             "1510": 15_000_000, "1600": 120_000_000},
}


def m(report, year, key):
    return next(r for r in report["reports"] if r["year"] == year)["metrics"][key]


def test_formulas_without_depreciation():
    r = analyze(FIN)
    assert r["available"] and r["years"] == ["2023", "2024"]
    assert m(r, "2024", "ebit")["value"] == 15e6 + 4e6 - 1e6
    assert m(r, "2023", "ebit")["value"] == 12e6 + 3e6 - 1e6  # знак расходов нормализован
    assert m(r, "2024", "ebitda")["value"] is None and "амортизац" in m(r, "2024", "ebitda")["note"]
    assert m(r, "2024", "debt_ebitda")["value"] is None
    assert m(r, "2024", "debt")["value"] == 40e6
    assert m(r, "2024", "net_debt")["value"] == 34e6
    assert m(r, "2024", "current_ratio")["value"] == pytest.approx(1.5)
    assert m(r, "2024", "revenue_yoy")["value"] == pytest.approx(0.2)
    assert m(r, "2023", "revenue_yoy")["value"] is None


def test_negative_ebitda_not_applicable():
    data = {"2024": {**FIN["2024"], "2300": -30_000_000, "amortization": 2_000_000}}
    r = analyze(data)
    assert m(r, "2024", "ebitda")["value"] == -30e6 + 4e6 - 1e6 + 2e6
    assert m(r, "2024", "debt_ebitda")["value"] is None and "неприменим" in m(r, "2024", "debt_ebitda")["note"]
    assert "EBIT неположителен" in r["flags"]


def test_no_data_cases():
    assert analyze({}, "company")["available"] is False
    assert analyze(FIN, "ip")["available"] is False


def test_ai_numbers_not_in_package_are_removed():
    pkg = ai.build_package(analyze(FIN), 1, "10.71", "ООО Тест", "7707083893")
    assert "компания" not in pkg  # уровень 1 — без названия и ИНН
    text = json.dumps({"summary": "Выручка 120 млн, рост 20%. Рентабельность 73%.", "strengths": ["EBIT 18 млн"],
                       "risks": ["Долг 999 млн"], "questions_for_manager": ["Какая амортизация?"], "limitations": [], "confidence": "средняя"},
                      ensure_ascii=False)
    out = ai.parse_and_validate(text, pkg)
    assert out["summary"] == "Выручка 120 млн, рост 20%."
    assert out["strengths"] == ["EBIT 18 млн"] and out["risks"] == [] and out["removed_count"] == 2
    with pytest.raises(ai.AIError):
        ai.parse_and_validate("не json", pkg)
    assert ai.build_package(analyze(FIN), 2, None, "ООО Тест", "7707083893")["компания"]["ИНН"] == "7707083893"


class FakeProviders:
    """Подмена API OpenAI и Anthropic: проверяет, что каждый запрос идёт со своим ключом."""

    def __init__(self):
        self.calls = []
        self.answer = {"summary": "Выручка 120 млн, рост 20%.", "strengths": [], "risks": [], "questions_for_manager": ["Какая амортизация?"],
                       "limitations": [], "confidence": "средняя"}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        auth = req.headers.get("authorization") or req.headers.get("x-api-key")
        self.calls.append((req.url.host, req.url.path, auth, req.content.decode() if req.content else ""))
        if "bad" in (auth or ""):
            return httpx.Response(401, json={"error": {"message": "Incorrect API key"}})
        if req.url.path.endswith("/models"):
            ids = ["gpt-4.1-mini", "gpt-4.1", "whisper-1"] if req.url.host == "api.openai.com" else ["claude-haiku-5-5", "claude-sonnet-5-5"]
            return httpx.Response(200, json={"data": [{"id": i} for i in ids]})
        text = json.dumps(self.answer, ensure_ascii=False)
        if req.url.host == "api.anthropic.com":
            return httpx.Response(200, json={"content": [{"type": "text", "text": text}], "usage": {"input_tokens": 10, "output_tokens": 5}})
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})


@pytest.fixture
def providers(monkeypatch):
    fake = FakeProviders()
    monkeypatch.setattr(ai_api, "gateway", ai.Gateway(transport=httpx.MockTransport(fake)))
    return fake


@pytest.fixture
def finances(monkeypatch):
    async def fin(self, inn):
        return checko_mod.CheckoResult(FIN if inn == SBER else {}, {"status": "ok"})

    monkeypatch.setattr(checko_mod.CheckoClient, "finances", fin)


async def add_client_with_finance(client, h):
    await client.post("/api/v1/integrations/checko", json={"api_key": "goodkey-1234ABCD"}, headers=h)
    cid = (await client.post("/api/v1/clients", json={"inn": SBER}, headers=h)).json()["id"]
    assert (await client.get(f"/api/v1/clients/{cid}/finance", headers=h)).json()["loaded"] is False
    r = (await client.post(f"/api/v1/clients/{cid}/finance/refresh", headers=h)).json()
    assert r["available"] and r["years"] == ["2023", "2024"]
    return cid


async def test_finance_works_without_ai(client, finances):
    h = await login(client, 1)
    cid = await add_client_with_finance(client, h)
    r = await client.post(f"/api/v1/clients/{cid}/finance/ai", json={}, headers=h)
    assert r.status_code == 409 and "не подключён" in r.json()["detail"]
    assert (await client.get(f"/api/v1/clients/{cid}/finance", headers=h)).json()["summary"]


async def test_each_user_uses_own_ai(client, finances, providers):
    a, b = await login(client, 1), await login(client, 2)
    ca = (await client.post("/api/v1/ai/connections", json={"provider": "openai", "api_key": "sk-userA-1111"}, headers=a)).json()
    cb = (await client.post("/api/v1/ai/connections", json={"provider": "anthropic", "api_key": "sk-ant-userB-2222"}, headers=b)).json()
    assert ca["status"] == "ok" and ca["model_id"] == "gpt-4.1-mini" and "whisper-1" not in ca["models"]
    assert cb["status"] == "ok" and cb["model_id"] == "claude-haiku-5-5" and cb["is_default"]
    assert ca["masked_secret"] == "••••1111" and "userA" not in json.dumps(ca)

    # B не видит и не может использовать подключение A
    assert [c["id"] for c in (await client.get("/api/v1/ai/connections", headers=b)).json()] == [cb["id"]]
    assert (await client.post(f"/api/v1/ai/connections/{ca['id']}/test", headers=b)).status_code == 404

    cid_a = await add_client_with_finance(client, a)
    providers.calls.clear()
    r = (await client.post(f"/api/v1/clients/{cid_a}/finance/ai", json={}, headers=a)).json()
    assert r["result"]["summary"].startswith("Выручка 120 млн")
    host, _, auth, body = providers.calls[-1]
    assert host == "api.openai.com" and auth == "Bearer sk-userA-1111"
    assert SBER not in body and "Сбер" not in body.upper()  # уровень 1: без ИНН и названия
    assert (await client.post(f"/api/v1/clients/{cid_a}/finance/ai", json={"connection_id": cb["id"]}, headers=a)).status_code == 404

    cid_b = await add_client_with_finance(client, b)
    r = (await client.post(f"/api/v1/clients/{cid_b}/finance/ai", json={}, headers=b)).json()
    assert providers.calls[-1][0] == "api.anthropic.com" and providers.calls[-1][2] == "sk-ant-userB-2222"
    assert r["connection"]["model_id"] == "claude-haiku-5-5"


async def test_bad_key_limit_and_delete(client, finances, providers):
    h = await login(client, 1)
    bad = (await client.post("/api/v1/ai/connections", json={"provider": "openai", "api_key": "sk-bad-0000"}, headers=h)).json()
    assert bad["status"] == "invalid_key" and "Ключ не принят" in bad["last_error"]
    good = (await client.post("/api/v1/ai/connections", json={"provider": "openai", "api_key": "sk-good-9999", "name": "Рабочий"}, headers=h)).json()
    r = (await client.put(f"/api/v1/ai/connections/{good['id']}", json={"is_default": True, "monthly_request_limit": 1}, headers=h)).json()
    assert r["is_default"] and r["monthly_request_limit"] == 1
    assert (await client.put(f"/api/v1/ai/connections/{good['id']}", json={"model_id": "nope"}, headers=h)).status_code == 422
    cid = await add_client_with_finance(client, h)
    assert (await client.post(f"/api/v1/clients/{cid}/finance/ai", json={}, headers=h)).status_code == 200
    n = len(providers.calls)
    r = await client.post(f"/api/v1/clients/{cid}/finance/ai", json={}, headers=h)
    assert r.status_code == 429 and len(providers.calls) == n  # лимит останавливает до внешнего API
    assert (await client.delete(f"/api/v1/ai/connections/{good['id']}", headers=h)).json()["ok"]
    left = (await client.get("/api/v1/ai/connections", headers=h)).json()
    assert [c["id"] for c in left] == [bad["id"]] and left[0]["is_default"]
    assert (await client.post("/api/v1/ai/connections", json={"provider": "evil", "api_key": "sk-1234567"}, headers=h)).status_code == 422


async def test_ai_number_check_through_api(client, finances, providers):
    h = await login(client, 1)
    await client.post("/api/v1/ai/connections", json={"provider": "openai", "api_key": "sk-good-9999"}, headers=h)
    cid = await add_client_with_finance(client, h)
    providers.answer = {"summary": "EBITDA 555 млн.", "strengths": ["Кредит одобрен"], "risks": [], "questions_for_manager": [], "limitations": []}
    r = await client.post(f"/api/v1/clients/{cid}/finance/ai", json={}, headers=h)
    assert r.status_code == 502 and "не прошёл проверку" in r.json()["detail"]


def test_providers_registry_is_https_allowlist():
    for p in ai.PROVIDERS.values():
        assert p.base_url.startswith("https://")
    assert set(ai.PROVIDERS) >= {"openai", "anthropic", "gigachat", "yandex"}
    assert COMPANIES  # фикстуры портфеля доступны
