from __future__ import annotations

from fastapi import FastAPI

from app.api import v1
from app.settings import settings

app = FastAPI(
    title="WBOZ",
    debug=settings.DEBUG,
    docs_url="/docs",
    redoc_url=None,
)


@app.get("/liveness", tags=["service"])
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(v1.router, prefix="/api/v1")
