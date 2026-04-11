"""Builds structured evaluation responses from rule engine results."""

from __future__ import annotations

from app.models.codex_objects import CodexObject
from app.models.schemas import (
    AbstainReason,
    ActiveTradeoff,
    ClarificationQuestion,
    ClarificationRequest,
    CoherenceCheck,
    DoctrineCoverage,
    EvaluationConditions,
    EvaluationOutcome,
    EvaluationResponse,
    Guidance,
    GuidanceAction,
    MetaEvaluation,
)
from app.services.rule_engine import RuleEngineResult


def build_response(
    result: RuleEngineResult,
    codex_objects: list[CodexObject],
    session_id: str,
    message_id: str,
) -> EvaluationResponse:
    """Convert a RuleEngineResult into a wire-format EvaluationResponse."""

    codex_refs = [obj.codex_id for obj in codex_objects] if codex_objects else None

    coherence = [
        CoherenceCheck(
            rule_id=c.rule_id,
            rule_name=c.rule_name,
            passed=c.passed,
            detail=c.detail,
            category=c.category,
        )
        for c in result.meta.coherence_checks
    ]

    meta = MetaEvaluation(
        trust_factors=result.meta.trust_factors,
        caution_factors=result.meta.caution_factors,
        doctrinal_grounding=result.meta.doctrinal_grounding,
        novel_situation=result.meta.novel_situation,
        response_completeness=result.meta.response_completeness,
        recommendation=result.meta.recommendation,
        coherence_checks=coherence,
    )

    if result.evaluation == "supported":
        return _build_supported(result, codex_refs, meta, session_id, message_id)
    elif result.evaluation == "conditional":
        return _build_conditional(result, codex_refs, meta, session_id, message_id)
    else:
        return _build_abstain(result, meta, session_id, message_id)


def _build_supported(
    result: RuleEngineResult,
    codex_refs: list[str] | None,
    meta: MetaEvaluation,
    session_id: str,
    message_id: str,
) -> EvaluationResponse:
    return EvaluationResponse(
        evaluation=EvaluationOutcome.SUPPORTED,
        session_id=session_id,
        message_id=message_id,
        doctrine_coverage=DoctrineCoverage(result.doctrine_coverage) if result.doctrine_coverage else None,
        coverage_basis=result.coverage_basis or None,
        guidance=_build_guidance(result.guidance_actions),
        codex_references=codex_refs,
        meta_evaluation=meta,
    )


def _build_conditional(
    result: RuleEngineResult,
    codex_refs: list[str] | None,
    meta: MetaEvaluation,
    session_id: str,
    message_id: str,
) -> EvaluationResponse:
    conditions = EvaluationConditions(
        unmet_preconditions=result.unmet_preconditions,
        required_observations=result.required_observations,
        active_tradeoffs=[
            ActiveTradeoff(**t) for t in result.active_tradeoffs
        ],
        constraints=result.constraint_notes,
    )

    return EvaluationResponse(
        evaluation=EvaluationOutcome.CONDITIONAL,
        session_id=session_id,
        message_id=message_id,
        doctrine_coverage=DoctrineCoverage(result.doctrine_coverage) if result.doctrine_coverage else None,
        coverage_basis=result.coverage_basis or None,
        coverage_gaps=result.coverage_gaps or None,
        guidance=_build_guidance(result.guidance_actions),
        conditions=conditions,
        codex_references=codex_refs,
        meta_evaluation=meta,
    )


def _build_abstain(
    result: RuleEngineResult,
    meta: MetaEvaluation,
    session_id: str,
    message_id: str,
) -> EvaluationResponse:
    abstain_reason = AbstainReason(result.abstain_reason) if result.abstain_reason else AbstainReason.INSUFFICIENT_INFORMATION

    clarification = None
    if abstain_reason == AbstainReason.INSUFFICIENT_INFORMATION and result.clarification_questions:
        clarification = ClarificationRequest(
            context_summary=result.context_summary,
            questions=[
                ClarificationQuestion(**q) for q in result.clarification_questions
            ],
        )

    return EvaluationResponse(
        evaluation=EvaluationOutcome.ABSTAIN,
        session_id=session_id,
        message_id=message_id,
        abstain_reason=abstain_reason,
        clarification=clarification,
        meta_evaluation=meta,
    )


def _build_guidance(raw_actions: list[dict]) -> Guidance | None:
    if not raw_actions:
        return None
    actions = [GuidanceAction(**a) for a in raw_actions]
    return Guidance(actions=actions)
