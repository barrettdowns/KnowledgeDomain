"""Pydantic request/response schemas aligned to CODEX primitives."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --- Enums ---

class ArtifactType(str, Enum):
    COURSE_OF_ACTION = "course_of_action"
    ANALYTIC_JUDGMENT = "analytic_judgment"
    TARGETING_RECOMMENDATION = "targeting_recommendation"
    COLLECTION_PLAN = "collection_plan"
    TRAINING_INTERVENTION = "training_intervention"
    SUSTAINMENT_OPTIMIZATION = "sustainment_optimization"
    OTHER = "other"


class EvaluationOutcome(str, Enum):
    SUPPORTED = "supported"
    CONDITIONAL = "conditional"
    ABSTAIN = "abstain"


class DoctrineCoverage(str, Enum):
    DIRECT = "direct"
    ANALOGOUS = "analogous"
    PARTIAL = "partial"


class AbstainReason(str, Enum):
    INSUFFICIENT_INFORMATION = "insufficient_information"
    NO_DOCTRINAL_COVERAGE = "no_doctrinal_coverage"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    ABANDONED = "abandoned"
    EXPIRED = "expired"


# --- Inbound Schemas ---

class ContextEnvelopeInput(BaseModel):
    echelon: str | None = None
    phase: str | None = None
    mission_type: str | None = None
    domain: str | None = None


class ProposedAction(BaseModel):
    sequence: int
    action: str
    parameters: dict[str, Any] = {}
    conditions: list[str] = []
    constraints: list[str] = []
    intended_effects: list[str] = []


class Precondition(BaseModel):
    condition: str
    status: bool | str = "unknown"


class Constraint(BaseModel):
    type: str
    value: str


class ClarificationAnswer(BaseModel):
    question_id: str
    answer: dict[str, Any]


class DecisionArtifact(BaseModel):
    """Inbound decision artifact from a requesting machine."""
    artifact_type: ArtifactType
    objective: str
    context_envelope: ContextEnvelopeInput | None = None
    situation: dict[str, Any] | None = None
    observations: list[str] = []
    proposed_actions: list[ProposedAction] = []
    preconditions: list[Precondition] = []
    constraints: list[Constraint] = []
    triggers: list[str] = []


class ClarificationResponse(BaseModel):
    """Inbound clarification answers from a requesting machine."""
    clarification_responses: list[ClarificationAnswer]


class InboundMessage(BaseModel):
    """Union of decision artifact and clarification response.
    Exactly one of artifact or clarification should be provided."""
    artifact: DecisionArtifact | None = None
    clarification: ClarificationResponse | None = None


# --- Outbound Schemas ---

class GuidanceAction(BaseModel):
    sequence: int
    action: str
    parameters: dict[str, Any] = {}
    conditions: list[str] = []
    constraints: list[str] = []


class Guidance(BaseModel):
    actions: list[GuidanceAction]


class ActiveTradeoff(BaseModel):
    tradeoff: str
    degradation: str
    compensation: str


class EvaluationConditions(BaseModel):
    unmet_preconditions: list[str] = []
    required_observations: list[str] = []
    active_tradeoffs: list[ActiveTradeoff] = []
    constraints: list[str] = []


class ClarificationQuestion(BaseModel):
    id: str
    question: str
    reason_needed: str
    expected_format: str


class ClarificationRequest(BaseModel):
    context_summary: str
    questions: list[ClarificationQuestion]


class CoherenceCheck(BaseModel):
    """Result of a doctrinal coherence rule -- does the overall response
    align with how the Army reasons, beyond individual field matching."""
    rule_id: str
    rule_name: str
    passed: bool
    detail: str
    category: str


class MetaEvaluation(BaseModel):
    """Per-response trust assessment -- tells the consumer why to trust
    or be cautious about this specific response."""
    trust_factors: list[str] = []
    caution_factors: list[str] = []
    doctrinal_grounding: str = "none"  # "direct", "analogous", "extrapolated", "none"
    novel_situation: bool = False
    response_completeness: float = 0.0
    recommendation: str = ""
    coherence_checks: list[CoherenceCheck] = []


class EvaluationResponse(BaseModel):
    """Outbound evaluation response to the requesting machine."""
    evaluation: EvaluationOutcome
    session_id: str
    message_id: str

    doctrine_coverage: DoctrineCoverage | None = None
    coverage_basis: list[str] | None = None
    coverage_gaps: list[str] | None = None

    guidance: Guidance | None = None
    conditions: EvaluationConditions | None = None
    codex_references: list[str] | None = None

    meta_evaluation: MetaEvaluation | None = None

    abstain_reason: AbstainReason | None = None
    clarification: ClarificationRequest | None = None


# --- Session Schemas ---

class SessionCreate(BaseModel):
    metadata: dict[str, Any] = {}


class SessionResponse(BaseModel):
    id: str
    status: SessionStatus
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime
    turn_count: int
    metadata: dict[str, Any] = {}


class SessionUpdate(BaseModel):
    status: SessionStatus


class SessionDetail(SessionResponse):
    messages: list[MessageSummary] = []


class MessageSummary(BaseModel):
    message_id: str
    direction: str
    timestamp: datetime
    content_preview: str


# Rebuild to resolve forward reference
SessionDetail.model_rebuild()
