from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.models.schemas import SessionCreate, SessionDetail, SessionResponse, SessionUpdate
from app.services import session_service

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(body: SessionCreate | None = None, db: AsyncSession = Depends(get_db)):
    metadata = body.metadata if body else {}
    return await session_service.create_session(db, metadata)


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    detail = await session_service.get_session_detail(db, session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Session not found")
    return detail


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(session_id: str, body: SessionUpdate, db: AsyncSession = Depends(get_db)):
    result = await session_service.update_session_status(db, session_id, body.status)
    if not result:
        raise HTTPException(status_code=404, detail="Session not found")
    return result
