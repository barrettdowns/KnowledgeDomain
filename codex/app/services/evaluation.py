"""CODEX evaluation pipeline -- the core reasoning orchestrator."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.interfaces.retriever import CodexRetriever
from app.models.database import MessageRecord, SessionRecord
from app.models.schemas import (
    EvaluationResponse,
    InboundMessage,
    SessionStatus,
)
from app.services.normalizer import normalize_inbound
from app.services.response_builder import build_response
from app.services.rule_engine import CodexRuleEngine

logger = logging.getLogger(__name__)


class EvaluationPipeline:
    def __init__(self, retriever: CodexRetriever, rule_engine: CodexRuleEngine):
        self._retriever = retriever
        self._engine = rule_engine

    async def process_message(
        self, session: SessionRecord, message: InboundMessage, db: AsyncSession
    ) -> EvaluationResponse:
        """Run the full CODEX evaluation pipeline for an inbound message."""

        # 1. Session checks
        if session.status != SessionStatus.ACTIVE.value:
            raise ValueError(f"Session {session.id} is not active (status: {session.status})")

        now = datetime.now(timezone.utc)
        if session.last_activity_at:
            last = session.last_activity_at
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            elapsed = (now - last).total_seconds()
            if elapsed > session.ttl_seconds:
                session.status = SessionStatus.EXPIRED.value
                await db.commit()
                raise ValueError(f"Session {session.id} has expired ({elapsed:.0f}s since last activity)")

        # 2. Normalize and accumulate context
        accumulated = session.get_accumulated_context()
        artifact, updated_context = normalize_inbound(message, accumulated)
        session.set_accumulated_context(updated_context)

        # Log inbound message
        inbound_msg_id = str(uuid.uuid4())
        inbound_record = MessageRecord(
            id=inbound_msg_id,
            session_id=session.id,
            direction="inbound",
            content=message.model_dump_json(),
        )
        db.add(inbound_record)

        # 3. Retrieve relevant CODEX objects
        codex_objects = await self._retriever.retrieve(artifact)

        # 4. Deterministic evaluation (rule engine)
        result = await self._engine.evaluate(artifact, codex_objects, updated_context)

        # 5. Gate logic -- override if max turns reached
        if (
            result.evaluation == "abstain"
            and result.abstain_reason == "insufficient_information"
            and session.turn_count >= settings.max_clarification_turns
        ):
            logger.info(f"Session {session.id} hit max clarification turns ({settings.max_clarification_turns})")
            result.evaluation = "conditional"
            result.abstain_reason = None
            result.reasoning_trace += " [MAX_TURNS_REACHED: delivering best-effort response]"
            if not result.doctrine_coverage:
                result.doctrine_coverage = "partial"
            result.rule_trace.append(f"GATE_MAX_TURNS: forced to conditional after {session.turn_count} turns")

        # 6. Build wire response
        outbound_msg_id = str(uuid.uuid4())
        response = build_response(result, codex_objects, session.id, outbound_msg_id)

        # 7. Log outbound message with full internal audit trail
        outbound_record = MessageRecord(
            id=outbound_msg_id,
            session_id=session.id,
            direction="outbound",
            content=response.model_dump_json(),
            internal_confidence=result.confidence,
            evaluation_outcome=result.evaluation,
            doctrine_coverage=result.doctrine_coverage,
            retrieved_codex_objects=json.dumps([obj.codex_id for obj in codex_objects]),
            precondition_validation=json.dumps({
                "unmet": result.unmet_preconditions,
                "missing_observations": result.required_observations,
            }),
            reasoning_trace=result.reasoning_trace,
            citations=json.dumps(result.coverage_basis),
            evaluation_rationale=result.reasoning_trace,
            causal_chain_evaluation=json.dumps(
                [cr.model_dump() for cr in result.causal_chain_results]
            ) if result.causal_chain_results else None,
            meta_evaluation_detail=json.dumps(result.meta.model_dump()),
            rule_engine_trace=json.dumps(result.rule_trace),
            flags=json.dumps({"max_turns_reached": session.turn_count >= settings.max_clarification_turns})
            if session.turn_count >= settings.max_clarification_turns else None,
        )
        db.add(outbound_record)

        # 8. Update session
        session.turn_count += 1
        session.last_activity_at = now
        session.updated_at = now
        await db.commit()

        return response
