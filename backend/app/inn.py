"""Проверка ИНН по контрольным цифрам (алгоритм ФНС)."""

_W10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_W11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_W12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _check(digits: list[int], weights: tuple[int, ...]) -> int:
    return sum(d * w for d, w in zip(digits, weights)) % 11 % 10


def normalize(raw: str) -> str:
    return "".join(ch for ch in raw if ch.isdigit())


def validate(inn: str) -> str | None:
    """Возвращает тип субъекта ('company' или 'ip') или None, если ИНН некорректен."""
    if not inn.isdigit():
        return None
    d = [int(c) for c in inn]
    if len(inn) == 10:
        return "company" if _check(d, _W10) == d[9] else None
    if len(inn) == 12:
        return "ip" if _check(d, _W11) == d[10] and _check(d, _W12) == d[11] else None
    return None
