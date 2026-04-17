from fastapi import APIRouter

from app.api.v1 import service

router = APIRouter()
router.include_router(service.router, prefix="/service", tags=["service"])
