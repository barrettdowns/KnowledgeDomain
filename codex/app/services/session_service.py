"""Session lifecycle management."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.database import MessageRecord, SessionRecord
from app.models.schemas import (
    MessageSummary,
    SessionDetail,
    SessionResponse,
    SessionStatus,
)


async def create_session(db: AsyncSession, metadata: dict[str, Any] | None = None) -> SessionResponse:
    record = SessionRecord(
        id=str(uuid.uuid4()),
        metadata_json=json.dumps(metadata or {}),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return _to_response(record)


async def get_session(db: AsyncSession, session_id: str) -> SessionResponse | None:
    record = await db.get(SessionRecord, session_id)
    if not record:
        return None
    _check_expiry(record)
    return _to_response(record)


async def get_session_detail(db: AsyncSession, session_id: str) -> SessionDetail | None:
    stmt = (
        select(SessionRecord)
        .options(selectinload(SessionRecord.messages))
        .where(SessionRecord.id == session_id)
    )
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()
    if not record:
        return None
    _check_expiry(record)

    messages = [
        MessageSummary(
            message_id=m.id,
            direction=m.direction,
            timestamp=m.timestamp,
            content_preview=_preview(m.content),
        )
        for m in record.messages
    ]

    return SessionDetail(
        id=record.id,
        status=SessionStatus(record.status),
        created_at=record.created_at,
        updated_at=record.updated_at,
        last_activity_at=record.last_activity_at,
        turn_count=record.turn_count,
        metadata=json.loads(record.metadata_json or "{}"),
        messages=messages,
    )


async def update_session_status(db: AsyncSession, session_id: str, status: SessionStatus) -> SessionResponse | None:
    record = await db.get(SessionRecord, session_id)
    if not record:
        return None
    record.status = status.value
    record.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(record)
    return _to_response(record)


async def get_session_record(db: AsyncSession, session_id: str) -> SessionRecord | None:
    record = await db.get(SessionRecord, session_id)
    if record:
        _check_expiry(record)
    return record


async def get_message_detail(db: AsyncSession, session_id: str, message_id: str) -> dict | None:
    stmt = select(MessageRecord).where(
        MessageRecord.id == message_id,
        MessageRecord.session_id == session_id,
    )
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()
    if not record:
        return None

    return {
        "message_id": record.id,
        "session_id": record.session_id,
        "direction": record.direction,
        "timestamp": record.timestamp.isoformat(),
        "content": json.loads(record.content),
        "internal_metadata": {
            "confidence": record.internal_confidence,
            "evaluation_outcome": record.evaluation_outcome,
            "doctrine_coverage": record.doctrine_coverage,
            "retrieved_codex_objects": json.loads(record.retrieved_codex_objects) if record.retrieved_codex_objects else None,
            "precondition_validation": json.loads(record.precondition_validation) if record.precondition_validation else None,
            "reasoning_trace": record.reasoning_trace,
            "citations": json.loads(record.citations) if record.citations else None,
            "evaluation_rationale": record.evaluation_rationale,
            "flags": json.loads(record.flags) if record.flags else None,
        },
    }


def _to_response(record: SessionRecord) -> SessionResponse:
    return SessionResponse(
        id=record.id,
        status=SessionStatus(record.status),
        created_at=record.created_at,
        updated_at=record.updated_at,
        last_activity_at=record.last_activity_at,
        turn_count=record.turn_count,
        metadata=json.loads(record.metadata_json or "{}"),
    )


def _check_expiry(record: SessionRecord) -> None:
    if record.status != "active":
        return
    now = datetime.now(timezone.utc)
    if record.last_activity_at:
        last = record.last_activity_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = (now - last).total_seconds()
        if elapsed > record.ttl_seconds:
            record.status = "expired"


def _preview(content: str, max_len: int = 120) -> str:
    if len(content) <= max_len:
        return content
    return content[:max_len] + "..."
