from fastapi import APIRouter

from app.settings import settings

router = APIRouter()


@router.get("/health")
async def service_health() -> dict[str, str]:
    return {
        "service": settings.APP_SERVICE_NAME,
        "environment": settings.APP_ENVIRONMENT,
        "status": "ok",
    }
