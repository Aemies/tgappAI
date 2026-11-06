from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .. import inn as innlib
from ..checko import CheckoError
from ..db import get_db
from ..models import User
from ..programs import facts_from_checko, load_catalog, match_all
from ..session import current_user
from .clients import _own_item, _profile
from .integrations import checko_for

router = APIRouter()


class CheckIn(BaseModel):
    client_id: int | None = None
    inn: str | None = Field(default=None, max_length=32)


@router.get("/programs")
async def catalog(user: User = Depends(current_user)):
    c = load_catalog()
    return {"rule_version": c["rule_version"], "programs": [{k: p.get(k) for k in ("id", "title", "authority", "official_url", "verified_at", "summary")} for p in c["programs"]]}


@router.post("/programs/check")
async def check(body: CheckIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if body.client_id:
        item = await _own_item(db, user, body.client_id)
        profile = await _profile(db, item)
        if profile is None:
            raise HTTPException(409, "Карточка клиента ещё не загружена: нажмите «Обновить» в карточке")
        subject_type, data, inn, name = item.subject_type, profile.payload, item.inn, (profile.summary or {}).get("name")
    elif body.inn:
        inn = innlib.normalize(body.inn)
        subject_type = innlib.validate(inn)
        if subject_type is None:
            raise HTTPException(422, "Некорректный ИНН")
        client = await checko_for(db, user)
        try:
            res = await (client.company(inn) if subject_type == "company" else client.entrepreneur(inn))
        except CheckoError as e:
            raise HTTPException(404 if e.not_found else 502, str(e))
        data = res.data if isinstance(res.data, dict) else {}
        if not data:
            raise HTTPException(404, "Не найдено в ЕГРЮЛ/ЕГРИП")
        from ..checko import summarize

        name = summarize(subject_type, data).get("name")
    else:
        raise HTTPException(422, "Укажите клиента или ИНН")
    facts = facts_from_checko(subject_type, data)
    return {"inn": inn, "name": name, "rule_version": load_catalog()["rule_version"], "results": match_all(facts),
            "disclaimer": "Предварительная оценка по открытым данным. Не является подтверждением права на господдержку и решением о финансировании."}
