"""SQLAlchemy models and async session factory."""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship

from app.config import settings


class Base(DeclarativeBase):
    pass


class SessionRecord(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    status = Column(String, default="active")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    last_activity_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    turn_count = Column(Integer, default=0)
    ttl_seconds = Column(Integer, default=settings.session_ttl_seconds)
    accumulated_context = Column(Text, default="{}")
    metadata_json = Column(Text, default="{}")

    messages = relationship("MessageRecord", back_populates="session", order_by="MessageRecord.timestamp")

    def get_accumulated_context(self) -> dict:
        return json.loads(self.accumulated_context or "{}")

    def set_accumulated_context(self, ctx: dict) -> None:
        self.accumulated_context = json.dumps(ctx)


class MessageRecord(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    direction = Column(String, nullable=False)  # "inbound" or "outbound"
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    content = Column(Text, nullable=False)

    # --- Human review fields (internal only, never on wire) ---
    internal_confidence = Column(Float, nullable=True)
    evaluation_outcome = Column(String, nullable=True)
    doctrine_coverage = Column(String, nullable=True)
    retrieved_codex_objects = Column(Text, nullable=True)
    precondition_validation = Column(Text, nullable=True)
    reasoning_trace = Column(Text, nullable=True)
    citations = Column(Text, nullable=True)
    evaluation_rationale = Column(Text, nullable=True)
    causal_chain_evaluation = Column(Text, nullable=True)
    meta_evaluation_detail = Column(Text, nullable=True)
    rule_engine_trace = Column(Text, nullable=True)
    flags = Column(Text, nullable=True)

    session = relationship("SessionRecord", back_populates="messages")


engine = create_async_engine(settings.database_url, echo=False)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    async with async_session_factory() as session:
        yield session
