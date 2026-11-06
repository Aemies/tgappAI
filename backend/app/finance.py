"""Финансовый экспресс-анализ по РСБУ (ТЗ, раздел 8). Только детерминированные формулы, без ИИ.

Данные: Checko /finances — словарь {год: {код строки: сумма в рублях}}. Каждое число в отчёте
указывает строку формы, из которой оно взято. Чего нет в отчётности — того нет и в отчёте:
EBITDA без раскрытой амортизации не рассчитывается, ноль не подставляется.
"""
from dataclasses import asdict, dataclass, field

METHOD_VERSION = "2026-11-06.1"
UNIT = "руб."
YEARS = 3

LINES = {
    "2110": "Выручка",
    "2120": "Себестоимость продаж",
    "2200": "Прибыль (убыток) от продаж",
    "2300": "Прибыль (убыток) до налогообложения",
    "2320": "Проценты к получению",
    "2330": "Проценты к уплате",
    "2400": "Чистая прибыль (убыток)",
    "1200": "Оборотные активы",
    "1250": "Денежные средства и эквиваленты",
    "1300": "Собственный капитал",
    "1410": "Долгосрочные заёмные средства",
    "1500": "Краткосрочные обязательства",
    "1510": "Краткосрочные заёмные средства",
    "1520": "Кредиторская задолженность",
    "1600": "Активы (баланс)",
}
# Расходы в разных выгрузках бывают со знаком минус (в форме — в скобках). Для формул берём модуль.
EXPENSE_LINES = {"2120", "2330"}
INCOME_ABS_LINES = {"2320"}
# Строки с амортизацией в кратких формах ГИР БО нет; если источник когда-то её отдаст — возьмём отсюда.
DEPRECIATION_KEYS = ("amortization", "Амортизация")

FORMULAS = {
    "ebit": "EBIT ≈ прибыль до налогообложения (2300) + проценты к уплате (2330) − проценты к получению (2320)",
    "ebitda": "EBITDA ≈ EBIT + амортизация ОС и НМА. Амортизации нет в доступной отчётности, поэтому EBITDA не рассчитывается",
    "debt": "Процентный долг = долгосрочные (1410) + краткосрочные (1510) заёмные средства. Кредиторская задолженность (1520) в долг не входит",
    "net_debt": "Чистый долг ≈ долг − денежные средства (1250)",
    "debt_ebitda": "Долг / EBITDA. Не рассчитывается без EBITDA; при EBITDA ≤ 0 — неприменим",
    "debt_ebit": "Долг / EBIT — замена Долг/EBITDA без амортизации, всегда выше настоящего Долг/EBITDA. При EBIT ≤ 0 — неприменим",
    "current_ratio": "Текущая ликвидность = оборотные активы (1200) / краткосрочные обязательства (1500)",
    "equity_ratio": "Доля собственного капитала = капитал (1300) / активы (1600)",
    "ebit_margin": "Рентабельность по EBIT = EBIT / выручка (2110)",
    "net_margin": "Чистая рентабельность = чистая прибыль (2400) / выручка (2110)",
    "revenue_yoy": "Рост выручки = выручка года / выручка прошлого года − 1",
}


@dataclass
class Metric:
    value: float | None
    note: str | None = None  # почему не рассчитано / на что обратить внимание


@dataclass
class YearReport:
    year: str
    lines: dict[str, float | None]
    metrics: dict[str, Metric] = field(default_factory=dict)


def _num(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _div(a: float | None, b: float | None, what: str) -> Metric:
    if a is None or b is None:
        return Metric(None, f"нет данных для расчёта ({what})")
    if b == 0:
        return Metric(None, "деление на ноль")
    return Metric(a / b)


def _year(year: str, raw: dict, prev: dict | None) -> YearReport:
    lines = {}
    for code in LINES:
        v = _num(raw.get(code))
        if v is not None and (code in EXPENSE_LINES or code in INCOME_ABS_LINES):
            v = abs(v)
        lines[code] = v
    m: dict[str, Metric] = {}
    pbt, ip, ir = lines["2300"], lines["2330"], lines["2320"]
    if pbt is None:
        m["ebit"] = Metric(None, "нет прибыли до налогообложения (2300)")
    else:
        notes = [n for n, v in (("проценты к уплате (2330)", ip), ("проценты к получению (2320)", ir)) if v is None]
        m["ebit"] = Metric(pbt + (ip or 0) - (ir or 0), ("нет строки: " + ", ".join(notes) + " — учтена как 0") if notes else None)
    dep = next((_num(raw.get(k)) for k in DEPRECIATION_KEYS if raw.get(k) is not None), None)
    ebit = m["ebit"].value
    if dep is None or ebit is None:
        m["ebitda"] = Metric(None, "не рассчитывается: нет данных об амортизации")
    else:
        m["ebitda"] = Metric(ebit + abs(dep))
    lt, st = lines["1410"], lines["1510"]
    if lt is None and st is None:
        m["debt"] = Metric(None, "нет строк 1410 и 1510")
    else:
        m["debt"] = Metric((lt or 0) + (st or 0))
    debt = m["debt"].value
    cash = lines["1250"]
    m["net_debt"] = Metric(None, "нет данных о долге или деньгах") if debt is None or cash is None else Metric(debt - cash)
    ebitda = m["ebitda"].value
    if ebitda is None:
        m["debt_ebitda"] = Metric(None, "N/A: EBITDA не рассчитана")
    elif ebitda <= 0:
        m["debt_ebitda"] = Metric(None, "неприменим: EBITDA неположительна")
    else:
        m["debt_ebitda"] = _div(debt, ebitda, "долг")
    if ebit is None or debt is None:
        m["debt_ebit"] = Metric(None, "нет данных")
    elif ebit <= 0:
        m["debt_ebit"] = Metric(None, "неприменим: EBIT неположителен")
    else:
        m["debt_ebit"] = Metric(debt / ebit, "без амортизации: настоящий Долг/EBITDA ниже")
    m["current_ratio"] = _div(lines["1200"], lines["1500"], "1200, 1500")
    m["equity_ratio"] = _div(lines["1300"], lines["1600"], "1300, 1600")
    m["ebit_margin"] = _div(ebit, lines["2110"], "EBIT, выручка")
    m["net_margin"] = _div(lines["2400"], lines["2110"], "2400, 2110")
    prev_rev = _num((prev or {}).get("2110"))
    rev = lines["2110"]
    if prev is None:
        m["revenue_yoy"] = Metric(None, "нет предыдущего года")
    elif rev is None or not prev_rev:
        m["revenue_yoy"] = Metric(None, "нет выручки за один из лет")
    else:
        m["revenue_yoy"] = Metric(rev / prev_rev - 1)
    return YearReport(year, lines, m)


def analyze(data: dict | None, subject_type: str = "company") -> dict:
    """Готовый отчёт для экрана и для ИИ. data — поле data ответа Checko /finances."""
    if subject_type != "company":
        return {"available": False, "reason": "У ИП нет публичной бухгалтерской отчётности — недостаточно данных для анализа"}
    years = sorted((y for y, v in (data or {}).items() if str(y).isdigit() and isinstance(v, dict) and v), key=int)
    if not years:
        return {"available": False, "reason": "Отчётности в ГИР БО нет (например, у банков и страховых или у новых компаний)"}
    picked = years[-YEARS:]
    reports = []
    for y in picked:
        i = years.index(y)
        reports.append(_year(y, data[y], data[years[i - 1]] if i > 0 else None))
    last = reports[-1]
    return {
        "available": True,
        "method_version": METHOD_VERSION,
        "unit": UNIT,
        "years": picked,
        "line_labels": LINES,
        "formulas": FORMULAS,
        "reports": [asdict(r) for r in reports],
        "summary": summary_text(reports),
        "questions": questions(last),
        "flags": flags(reports),
        "disclaimer": "Экспресс-анализ по открытой отчётности РСБУ. Не кредитное решение и не заменяет финансовую экспертизу.",
    }


def fmt_money(v: float | None) -> str:
    if v is None:
        return "—"
    a = abs(v)
    if a >= 1e9:
        s = f"{v / 1e9:.1f} млрд ₽"
    elif a >= 1e6:
        s = f"{v / 1e6:.1f} млн ₽"
    elif a >= 1e3:
        s = f"{v / 1e3:.0f} тыс. ₽"
    else:
        s = f"{v:.0f} ₽"
    return s.replace(".", ",")


def fmt_pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.1f}%".replace(".", ",")


def fmt_x(v: float | None) -> str:
    return "—" if v is None else f"{v:.2f}".replace(".", ",")


def summary_text(reports: list[YearReport]) -> list[str]:
    """Сводка без ИИ: только то, что следует из чисел."""
    last = reports[-1]
    L, M = last.lines, last.metrics
    out = []
    if L["2110"] is not None:
        s = f"Выручка за {last.year} год — {fmt_money(L['2110'])}"
        if M["revenue_yoy"].value is not None:
            s += f", {'рост' if M['revenue_yoy'].value >= 0 else 'снижение'} на {fmt_pct(abs(M['revenue_yoy'].value))} к прошлому году"
        out.append(s + ".")
    if L["2400"] is not None:
        out.append(f"{'Чистая прибыль' if L['2400'] >= 0 else 'Чистый убыток'} — {fmt_money(abs(L['2400']))}.")
    if M["ebit"].value is not None:
        s = f"EBIT — {fmt_money(M['ebit'].value)}."
        if M["ebitda"].value is None:
            s += " EBITDA не рассчитывается: в отчётности нет амортизации."
        out.append(s)
    if M["debt"].value is not None:
        s = f"Процентный долг — {fmt_money(M['debt'].value)}"
        if M["debt_ebit"].value is not None:
            s += f", долг/EBIT — {fmt_x(M['debt_ebit'].value)}"
        out.append(s + ".")
    if M["current_ratio"].value is not None:
        out.append(f"Текущая ликвидность — {fmt_x(M['current_ratio'].value)}, доля собственного капитала — {fmt_pct(M['equity_ratio'].value)}.")
    return out


def flags(reports: list[YearReport]) -> list[str]:
    """Нейтральные отметки «нужен дополнительный анализ» — без банковского рейтинга."""
    last = reports[-1]
    L, M = last.lines, last.metrics
    f = []
    if L["2400"] is not None and L["2400"] < 0:
        f.append("Убыток в последнем году")
    if L["1300"] is not None and L["1300"] < 0:
        f.append("Отрицательный собственный капитал")
    if M["current_ratio"].value is not None and M["current_ratio"].value < 1:
        f.append("Краткосрочные обязательства больше оборотных активов")
    if M["revenue_yoy"].value is not None and M["revenue_yoy"].value < -0.2:
        f.append("Выручка снизилась больше чем на 20%")
    if M["ebit"].value is not None and M["ebit"].value <= 0:
        f.append("EBIT неположителен")
    return f


def questions(last: YearReport) -> list[str]:
    q = ["Есть ли отчётность за текущий год или промежуточная (квартальная)?",
         "Какова амортизация основных средств и НМА за год? Без неё EBITDA не посчитать.",
         "Есть ли лизинг, поручительства и займы от связанных компаний (в балансе их может не быть в 1410/1510)?"]
    if last.lines["2400"] is not None and last.lines["2400"] < 0:
        q.append("С чем связан убыток последнего года и что ожидается в текущем?")
    if last.metrics["revenue_yoy"].value is not None and last.metrics["revenue_yoy"].value < 0:
        q.append("Почему снизилась выручка?")
    q.append("Какой график погашения текущих кредитов?")
    return q
