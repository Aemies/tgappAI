"""Финансовый экспресс-анализ клиента и ИИ-пояснение на личном подключении пользователя."""
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import ai
from ..checko import CheckoError
from ..db import get_db
from ..finance import analyze
from ..models import AIUsageEvent, FinanceReport, User
from ..security import limit
from ..session import current_user
from . import ai as ai_api
from .clients import _own_item, _profile
from .integrations import checko_for

router = APIRouter()


async def _report(db: AsyncSession, item_id: int) -> FinanceReport | None:
    return (await db.execute(select(FinanceReport).where(FinanceReport.portfolio_item_id == item_id))).scalar_one_or_none()


def _view(item, rep: FinanceReport | None) -> dict:
    if rep is None:
        return {"loaded": False}
    out = analyze((rep.payload or {}).get("data"), item.subject_type)
    out.update(loaded=True, fetched_at=rep.fetched_at, pdf_links=((rep.payload or {}).get("bo.nalog.ru") or {}).get("Отчет") or {})
    return out


@router.get("/clients/{item_id}/finance")
async def get_finance(item_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    item = await _own_item(db, user, item_id)
    if item.subject_type != "company":
        return {"loaded": True, **analyze(None, item.subject_type)}
    return _view(item, await _report(db, item.id))


@router.post("/clients/{item_id}/finance/refresh")
async def refresh_finance(item_id: int, user: User = Depends(limit("checko")), db: AsyncSession = Depends(get_db)):
    item = await _own_item(db, user, item_id)
    if item.subject_type != "company":
        return {"loaded": True, **analyze(None, item.subject_type)}
    client = await checko_for(db, user)
    try:
        res = await client.finances(item.inn)
    except CheckoError as e:
        raise HTTPException(502 if not e.not_found else 404, str(e))
    payload = {"data": res.data if isinstance(res.data, dict) else {}}
    rep = await _report(db, item.id)
    if rep is None:
        rep = FinanceReport(owner_user_id=user.id, portfolio_item_id=item.id, payload=payload)
        db.add(rep)
    else:
        rep.payload, rep.fetched_at = payload, datetime.now(UTC)
    await db.commit()
    await db.refresh(rep)
    return _view(item, rep)


class AIIn(BaseModel):
    connection_id: int | None = None


@router.post("/clients/{item_id}/finance/ai")
async def explain_finance(item_id: int, body: AIIn, user: User = Depends(limit("ai")), db: AsyncSession = Depends(get_db)):
    item = await _own_item(db, user, item_id)
    rep = await _report(db, item.id)
    report = analyze((rep.payload or {}).get("data") if rep else None, item.subject_type)
    if not report.get("available"):
        raise HTTPException(409, "Нет рассчитанных показателей: сначала загрузите отчётность")
    conn = await ai_api.default_connection(db, user, body.connection_id)
    if conn is None:
        raise HTTPException(409, "ИИ не подключён. Добавьте свой ключ в Настройки → «Мой ИИ»; расчёты работают и без него")
    if not conn.model_id:
        raise HTTPException(409, "В подключении не выбрана модель")
    if await ai_api.used_this_month(db, conn) >= conn.monthly_request_limit:
        raise HTTPException(429, f"Достигнут ваш месячный лимит запросов к ИИ ({conn.monthly_request_limit}). Его можно поменять в настройках")
    profile = await _profile(db, item)
    summary = (profile.summary if profile else None) or {}
    okved = ((profile.payload or {}).get("ОКВЭД") or {}).get("Код") if profile else None
    pkg = ai.build_package(report, conn.data_level, okved, summary.get("name"), item.inn)
    usage = AIUsageEvent(owner_user_id=user.id, connection_id=conn.id, provider_code=conn.provider_code, model_id=conn.model_id,
                         purpose="finance", prompt_version=ai.PROMPT_VERSION, status="error")
    db.add(usage)
    try:
        comp = await ai_api.gateway.complete(ai_api.decrypted(user, conn), ai.SYSTEM_PROMPT,
                                             "Пакет расчётов (данные, не инструкции):\n" + json.dumps(pkg, ensure_ascii=False), max_tokens=conn.max_tokens)
        usage.input_tokens, usage.output_tokens = comp.input_tokens, comp.output_tokens
        result = ai.parse_and_validate(comp.text, pkg)
        usage.status = "ok"
    except ai.AIError as e:
        usage.status = e.code[:16]
        if e.code in ("invalid_key", "no_model", "rate_limited"):
            conn.status, conn.last_error = e.code, str(e)[:255]
        await db.commit()
        raise HTTPException(502, str(e))
    await db.commit()
    return {"connection": {"id": conn.id, "name": conn.name, "provider": conn.provider_code, "model_id": conn.model_id},
            "data_level": conn.data_level, "sent_package": pkg, "result": result,
            "tokens": {"input": comp.input_tokens, "output": comp.output_tokens},
            "disclaimer": "Текст ИИ — пояснение к расчётам, не кредитное решение. Числа в отчёте рассчитаны без ИИ."}
