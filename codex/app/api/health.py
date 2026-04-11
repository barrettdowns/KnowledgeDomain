from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "codex-warbrain-conversation-api", "version": "0.1.0"}
