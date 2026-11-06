"""Подбор госпрограмм: формальные правила из каталога + данные компании из Checko (ТЗ, раздел 7).

Статусы результата:
- LIKELY_MATCH — все проверяемые критерии выполнены (остаются вопросы к клиенту);
- NEEDS_MORE_INFO — каких-то данных нет, «не подходит» из этого не следует;
- KNOWN_MISMATCH — достоверно не выполнен хотя бы один критерий;
- PROGRAM_UNVERIFIED — условия программы давно не перепроверялись, полагаться на них нельзя.

Условия программ не зашиты в код: они лежат в programs_catalog.json с источником и датой проверки.
"""
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

CATALOG = Path(__file__).with_name("programs_catalog.json")

PASS, FAIL, UNKNOWN, ASK = "pass", "fail", "unknown", "ask"
STATUS_ORDER = {"LIKELY_MATCH": 0, "NEEDS_MORE_INFO": 1, "PROGRAM_UNVERIFIED": 2, "KNOWN_MISMATCH": 3}
MSP_ALL = ["МИКРОПРЕДПРИЯТИЕ", "МАЛОЕ ПРЕДПРИЯТИЕ", "СРЕДНЕЕ ПРЕДПРИЯТИЕ"]


@dataclass
class Check:
    result: str  # pass | fail | unknown | ask
    text: str


@dataclass
class ProgramResult:
    program_id: str
    title: str
    authority: str
    official_url: str
    verified_at: str
    status: str
    checks: list[Check] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    note: str = "Предварительное совпадение, не подтверждение права на поддержку"


@lru_cache
def load_catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


@dataclass
class Facts:
    subject_type: str
    status: str | None
    msp_category: str | None
    region_code: str | None
    okveds: list[str]
    registered: date | None
    bankruptcy: bool | None
    bad_supplier: bool | None
    employees: int | None


def facts_from_checko(subject_type: str, data: dict) -> Facts:
    def code(v):
        return v.get("Код") if isinstance(v, dict) else None

    okveds = [c for c in [code(data.get("ОКВЭД"))] + [code(x) for x in data.get("ОКВЭДДоп") or []] if c]
    reg = data.get("ДатаРег") or data.get("ДатаОГРНИП")
    try:
        registered = date.fromisoformat(reg) if reg else None
    except ValueError:
        registered = None
    rmsp = data.get("РМСП")
    return Facts(
        subject_type=subject_type,
        status=(data.get("Статус") or {}).get("Наим") if isinstance(data.get("Статус"), dict) else data.get("Статус"),
        msp_category=(rmsp or {}).get("Кат") if isinstance(rmsp, dict) else None,
        region_code=code(data.get("Регион")),
        okveds=okveds,
        registered=registered,
        bankruptcy=bool(data.get("ЕФРСБ")) if "ЕФРСБ" in data else None,
        bad_supplier=data.get("НедобПост") if isinstance(data.get("НедобПост"), bool) else None,
        employees=data.get("СЧР") if isinstance(data.get("СЧР"), int) else None,
    )


def _months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month) - (1 if b.day < a.day else 0)


def _rule(rule: dict, f: Facts, today: date) -> Check:
    t = rule["type"]
    src = f" ({rule['source']})" if rule.get("source") else ""
    if t == "entity_types":
        names = {"company": "юрлицо", "ip": "ИП"}
        ok = f.subject_type in rule["values"]
        return Check(PASS if ok else FAIL, f"Тип заявителя: {names.get(f.subject_type, f.subject_type)}" + ("" if ok else " — программа для: " + ", ".join(names.get(v, v) for v in rule["values"])) + src)
    if t == "msp_registry":
        cats = rule.get("categories") or MSP_ALL
        if f.msp_category is None:
            return Check(UNKNOWN, "Нет данных о включении в реестр МСП" + src)
        ok = f.msp_category.upper() in cats
        return Check(PASS if ok else FAIL, f"Реестр МСП: {f.msp_category.lower()}" + ("" if ok else " — категория не подходит") + src)
    if t == "status_active":
        if not f.status:
            return Check(UNKNOWN, "Статус в ЕГРЮЛ/ЕГРИП неизвестен")
        ok = f.status.lower().startswith("действ")
        return Check(PASS if ok else FAIL, f"Статус: {f.status}")
    if t == "no_bankruptcy":
        if f.bankruptcy is None:
            return Check(UNKNOWN, "Нет данных о сообщениях о банкротстве")
        return Check(FAIL if f.bankruptcy else PASS, "Есть сообщения о банкротстве (ЕФРСБ)" if f.bankruptcy else "Сообщений о банкротстве нет")
    if t == "not_bad_supplier":
        if f.bad_supplier is None:
            return Check(UNKNOWN, "Нет данных о реестре недобросовестных поставщиков")
        return Check(FAIL if f.bad_supplier else PASS, "В реестре недобросовестных поставщиков" if f.bad_supplier else "Нет в реестре недобросовестных поставщиков")
    if t == "okved_prefixes":
        if not f.okveds:
            return Check(UNKNOWN, "ОКВЭД неизвестен")
        prefixes = rule["values"]
        field_ = rule.get("field", "main")
        codes = f.okveds[:1] if field_ == "main" else f.okveds
        hit = [c for c in codes if any(c == p or c.startswith(p + ".") for p in prefixes)]
        label = rule.get("label", "ОКВЭД")
        if rule.get("mode", "include") == "include":
            return Check(PASS if hit else FAIL, f"{label}: {', '.join(hit) if hit else codes[0] + ' не входит в перечень'}" + src)
        return Check(FAIL if hit else PASS, f"{label}: {'исключённый вид деятельности ' + ', '.join(hit) if hit else 'ограничений нет'}" + src)
    if t == "min_age_months":
        if f.registered is None:
            return Check(UNKNOWN, "Дата регистрации неизвестна")
        m = _months_between(f.registered, today)
        ok = m >= rule["value"]
        return Check(PASS if ok else FAIL, f"Срок с регистрации: {m // 12} г. {m % 12} мес." + ("" if ok else f" — нужно от {rule['value']} мес.") + src)
    if t == "regions":
        if not f.region_code:
            return Check(UNKNOWN, "Регион неизвестен")
        ok = f.region_code in rule["values"]
        return Check(PASS if ok else FAIL, f"Регион {f.region_code}" + ("" if ok else " вне перечня программы") + src)
    if t == "ask":
        return Check(ASK, rule["text"] + src)
    if t == "any_of":
        # Достаточно одного основания (например, приоритетная отрасль ИЛИ регион ИЛИ статус МТК).
        subs = [_rule(r, f, today) for r in rule["rules"]]
        label = rule.get("label", "Одно из оснований")
        passed = [c for c in subs if c.result == PASS]
        if passed:
            return Check(PASS, f"{label}: {passed[0].text}" + src)
        open_ = [c.text for c in subs if c.result in (UNKNOWN, ASK)]
        if open_:
            return Check(UNKNOWN, f"{label}: по открытым данным не подтверждено, уточните — " + "; ".join(open_) + src)
        return Check(FAIL, f"{label}: ни одно не выполнено (" + "; ".join(c.text for c in subs) + ")" + src)
    return Check(UNKNOWN, f"Правило «{t}» не поддерживается")


def evaluate(program: dict, f: Facts, today: date | None = None) -> ProgramResult:
    today = today or date.today()
    checks = [_rule(r, f, today) for r in program.get("rules", [])]
    verified = date.fromisoformat(program["verified_at"])
    stale = (today - verified).days > program.get("review_days", 90)
    expired = bool(program.get("valid_to")) and date.fromisoformat(program["valid_to"]) < today
    if any(c.result == FAIL for c in checks):
        status = "KNOWN_MISMATCH"
    elif stale or expired or program.get("unverified"):
        status = "PROGRAM_UNVERIFIED"
        if expired:
            msg = "Срок действия программы истёк"
        elif stale:
            msg = "Условия программы давно не перепроверялись — сверьте на официальном сайте"
        else:
            msg = "На официальной странице не все условия — сверьте перед тем, как предлагать клиенту"
        checks.append(Check(UNKNOWN, msg))
    elif any(c.result == UNKNOWN for c in checks):
        status = "NEEDS_MORE_INFO"
    else:
        status = "LIKELY_MATCH"
    return ProgramResult(program_id=program["id"], title=program["title"], authority=program["authority"], official_url=program["official_url"],
                         verified_at=program["verified_at"], status=status, checks=checks, summary=program.get("summary", {}))


def match_all(f: Facts, today: date | None = None) -> list[dict]:
    res = [evaluate(p, f, today) for p in load_catalog()["programs"]]
    res.sort(key=lambda r: STATUS_ORDER[r.status])
    return [asdict(r) for r in res]
