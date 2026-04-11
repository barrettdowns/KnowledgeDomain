from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.models.schemas import EvaluationResponse, InboundMessage
from app.services import session_service

router = APIRouter(prefix="/sessions/{session_id}/messages", tags=["messages"])


@router.post("", response_model=EvaluationResponse)
async def submit_message(
    session_id: str,
    body: InboundMessage,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    session = await session_service.get_session_record(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status != "active":
        raise HTTPException(
            status_code=409,
            detail=f"Session is not active (status: {session.status})",
        )

    if not body.artifact and not body.clarification:
        raise HTTPException(
            status_code=422,
            detail="Request must contain either an 'artifact' or a 'clarification' field",
        )

    pipeline = request.app.state.evaluation_pipeline
    try:
        response = await pipeline.process_message(session, body, db)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return response


@router.get("/{message_id}")
async def get_message(
    session_id: str,
    message_id: str,
    db: AsyncSession = Depends(get_db),
):
    detail = await session_service.get_message_detail(db, session_id, message_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Message not found")
    return detail
