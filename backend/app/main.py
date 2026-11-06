from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import auth, clients, integrations, me, monitoring
from .config import get_settings

app = FastAPI(title="Клиентский радар", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
app.include_router(me.router, prefix="/api/v1", tags=["me"])
app.include_router(integrations.router, prefix="/api/v1", tags=["integrations"])
app.include_router(clients.router, prefix="/api/v1", tags=["clients"])
app.include_router(monitoring.router, prefix="/api/v1", tags=["monitoring"])


@app.get("/api/health")
async def health():
    return {"status": "ok"}


_static = get_settings().static_dir
if _static and Path(_static, "index.html").is_file():
    app.mount("/", StaticFiles(directory=_static, html=True), name="miniapp")
