from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.messages import router as messages_router
from app.api.sessions import router as sessions_router

v1_router = APIRouter(prefix="/v1")
v1_router.include_router(health_router)
v1_router.include_router(sessions_router)
v1_router.include_router(messages_router)
