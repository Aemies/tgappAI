from fastapi import FastAPI

from .api import auth, me

app = FastAPI(title="Клиентский радар", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
app.include_router(me.router, prefix="/api/v1", tags=["me"])


@app.get("/api/health")
async def health():
    return {"status": "ok"}
