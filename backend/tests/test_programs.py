from datetime import date

from app import checko as checko_mod
from app.programs import Facts, evaluate, load_catalog, match_all

from .test_portfolio import login, setup  # noqa: F401  (фикстура с подменой Checko)

TODAY = date(2026, 11, 6)
# Сокращённая реальная карточка среднего пищевого производства из Нижегородской области (ответ Checko).
SME = {"НаимСокр": "ООО \"ХЛЕБ\"", "Статус": {"Наим": "Действует"}, "Регион": {"Код": "52", "Наим": "Нижегородская область"},
       "ОКВЭД": {"Код": "10.72.1"}, "ОКВЭДДоп": [{"Код": "46.36.3"}], "ДатаРег": "2009-05-18",
       "РМСП": {"Кат": "СРЕДНЕЕ ПРЕДПРИЯТИЕ"}, "ЕФРСБ": [], "НедобПост": False, "СЧР": 147}


def facts(**kw):
    base = dict(subject_type="company", status="Действует", msp_category="МАЛОЕ ПРЕДПРИЯТИЕ", region_code="52", okveds=["25.11"],
                registered=date(2015, 1, 1), bankruptcy=False, bad_supplier=False, employees=20)
    base.update(kw)
    return Facts(**base)


def by_id(results):
    return {r["program_id"]: r for r in results}


def test_catalog_has_sources_and_dates():
    c = load_catalog()
    assert c["rule_version"]
    for p in c["programs"]:
        assert p["official_url"].startswith("https://") and date.fromisoformat(p["verified_at"])


def test_small_manufacturer_matches_leasing_and_credit():
    r = by_id(match_all(facts(), TODAY))
    assert r["psk-mer-invest"]["status"] == "LIKELY_MATCH"
    assert r["msp-leasing-manufacturing"]["status"] == "LIKELY_MATCH"
    assert r["msp-guarantees"]["status"] == "PROGRAM_UNVERIFIED"


def test_medium_company_not_for_leasing():
    r = by_id(match_all(facts(msp_category="СРЕДНЕЕ ПРЕДПРИЯТИЕ"), TODAY))
    assert r["msp-leasing-manufacturing"]["status"] == "KNOWN_MISMATCH"
    assert r["psk-mer-invest"]["status"] == "LIKELY_MATCH"


def test_bank_excluded_and_bankrupt_excluded():
    r = by_id(match_all(facts(okveds=["64.19"]), TODAY))
    assert r["psk-mer-invest"]["status"] == "KNOWN_MISMATCH"
    r = by_id(match_all(facts(bankruptcy=True), TODAY))
    assert r["psk-mer-invest"]["status"] == "KNOWN_MISMATCH"


def test_non_priority_sector_needs_info_not_mismatch():
    # Торговля не в приоритетных отраслях, но клиент может пройти как МТК — значит «уточнить», а не «не подходит».
    r = by_id(match_all(facts(okveds=["47.11"]), TODAY))
    assert r["psk-mer-invest"]["status"] == "NEEDS_MORE_INFO"
    # Тот же клиент в Краснодарском крае проходит по региону.
    r = by_id(match_all(facts(okveds=["47.11"], region_code="23"), TODAY))
    assert r["psk-mer-invest"]["status"] == "LIKELY_MATCH"


def test_missing_registry_data_is_unknown():
    r = by_id(match_all(facts(msp_category=None), TODAY))
    assert r["psk-mer-invest"]["status"] == "NEEDS_MORE_INFO"


def test_stale_program_is_unverified():
    p = next(p for p in load_catalog()["programs"] if p["id"] == "psk-mer-invest")
    assert evaluate(p, facts(), date(2027, 6, 1)).status == "PROGRAM_UNVERIFIED"
    assert evaluate({**p, "valid_to": "2026-01-01"}, facts(), TODAY).status == "PROGRAM_UNVERIFIED"
    # Несовпадение важнее устаревания: явный отказ виден всегда.
    assert evaluate(p, facts(bankruptcy=True), date(2027, 6, 1)).status == "KNOWN_MISMATCH"


async def test_check_api_by_client_and_inn(client, setup, monkeypatch):
    from .test_portfolio import COMPANIES, SBER

    monkeypatch.setitem(COMPANIES, SBER, SME)
    h = await login(client, 1)
    assert (await client.post("/api/v1/programs/check", json={"inn": SBER}, headers=h)).status_code == 409  # нет ключа
    await client.post("/api/v1/integrations/checko", json={"api_key": "goodkey-1234ABCD"}, headers=h)
    r = (await client.post("/api/v1/programs/check", json={"inn": SBER}, headers=h)).json()
    assert r["name"] == "ООО \"ХЛЕБ\"" and r["disclaimer"]
    assert by_id(r["results"])["psk-mer-invest"]["status"] == "LIKELY_MATCH"

    cid = (await client.post("/api/v1/clients", json={"inn": SBER}, headers=h)).json()["id"]
    calls_before = len(setup)
    r = (await client.post("/api/v1/programs/check", json={"client_id": cid}, headers=h)).json()
    assert len(setup) == calls_before  # по клиенту из портфеля Checko не вызывается
    assert by_id(r["results"])["msp-leasing-manufacturing"]["status"] == "KNOWN_MISMATCH"

    other = await login(client, 2)
    assert (await client.post("/api/v1/programs/check", json={"client_id": cid}, headers=other)).status_code == 404
    assert (await client.post("/api/v1/programs/check", json={"inn": "7707083894"}, headers=h)).status_code == 422
    assert (await client.get("/api/v1/programs", headers=h)).json()["programs"]
