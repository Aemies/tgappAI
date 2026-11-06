from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import ai, auth, clients, finance, integrations, me, monitoring, programs
from .config import get_settings
from .security import SecurityMiddleware, setup_logging

setup_logging()
_docs = get_settings().api_docs

app = FastAPI(title="Клиентский радар", version="0.6.0", docs_url="/api/docs" if _docs else None, redoc_url=None,
              openapi_url="/api/openapi.json" if _docs else None)
# CORS не включаем намеренно: кабинет и API на одном адресе, чужие сайты не получат ответов
app.add_middleware(SecurityMiddleware)
app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
app.include_router(me.router, prefix="/api/v1", tags=["me"])
app.include_router(integrations.router, prefix="/api/v1", tags=["integrations"])
app.include_router(clients.router, prefix="/api/v1", tags=["clients"])
app.include_router(monitoring.router, prefix="/api/v1", tags=["monitoring"])
app.include_router(programs.router, prefix="/api/v1", tags=["programs"])
app.include_router(finance.router, prefix="/api/v1", tags=["finance"])
app.include_router(ai.router, prefix="/api/v1", tags=["ai"])


@app.get("/api/health")
async def health():
    return {"status": "ok"}


_static = get_settings().static_dir
if _static and Path(_static, "index.html").is_file():
    app.mount("/", StaticFiles(directory=_static, html=True), name="miniapp")
