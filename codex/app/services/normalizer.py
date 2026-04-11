"""Artifact normalization and context accumulation."""

from __future__ import annotations

from app.models.schemas import ClarificationResponse, DecisionArtifact, InboundMessage


def normalize_inbound(message: InboundMessage, accumulated_context: dict) -> tuple[DecisionArtifact, dict]:
    """Normalize an inbound message and merge with accumulated session context.

    Returns the working artifact and the updated accumulated context.
    """
    if message.artifact:
        artifact = message.artifact
        ctx = _merge_artifact_into_context(artifact, accumulated_context)
        return artifact, ctx

    if message.clarification:
        # Merge clarification first so the rebuilt artifact reflects
        # the newly provided information in the same evaluation turn.
        ctx = _merge_clarification_into_context(message.clarification, accumulated_context)
        artifact = _rebuild_artifact_from_context(ctx, message.clarification)
        return artifact, ctx

    raise ValueError("InboundMessage must contain either an artifact or a clarification response")


def _merge_artifact_into_context(artifact: DecisionArtifact, existing: dict) -> dict:
    ctx = dict(existing)
    ctx["artifact_type"] = artifact.artifact_type.value
    ctx["objective"] = artifact.objective

    if artifact.context_envelope:
        ctx["context_envelope"] = artifact.context_envelope.model_dump(exclude_none=True)
    if artifact.situation:
        ctx.setdefault("situation", {}).update(artifact.situation)
    if artifact.observations:
        ctx.setdefault("observations", []).extend(artifact.observations)
        ctx["observations"] = list(set(ctx["observations"]))
    if artifact.proposed_actions:
        ctx["proposed_actions"] = [a.model_dump() for a in artifact.proposed_actions]
    if artifact.preconditions:
        ctx["preconditions"] = [p.model_dump() for p in artifact.preconditions]
    if artifact.constraints:
        ctx["constraints"] = [c.model_dump() for c in artifact.constraints]
    if artifact.triggers:
        ctx.setdefault("triggers", []).extend(artifact.triggers)
        ctx["triggers"] = list(set(ctx["triggers"]))

    return ctx


def _merge_clarification_into_context(clarification: ClarificationResponse, existing: dict) -> dict:
    ctx = dict(existing)
    responses = ctx.setdefault("clarification_responses", {})
    for answer in clarification.clarification_responses:
        responses[answer.question_id] = answer.answer

        for key, value in answer.answer.items():
            if key in ("composition", "strength", "friendly_forces"):
                ctx.setdefault("situation", {}).setdefault("friendly_forces", {}).update(
                    {key: value} if isinstance(value, str) else value if isinstance(value, dict) else {key: str(value)}
                )
            elif key in ("enemy_type", "enemy_size", "enemy_forces"):
                ctx.setdefault("situation", {}).setdefault("enemy_forces", {}).update(
                    {key: value} if isinstance(value, str) else value if isinstance(value, dict) else {key: str(value)}
                )
            elif key == "civilian_present":
                ctx.setdefault("situation", {})["civilian_present"] = value
            elif key == "context_envelope":
                if isinstance(value, dict):
                    ctx.setdefault("context_envelope", {}).update(value)

    return ctx


def _rebuild_artifact_from_context(accumulated_context: dict, clarification: ClarificationResponse) -> DecisionArtifact:
    """Rebuild a DecisionArtifact from accumulated context for re-evaluation."""
    from app.models.schemas import ArtifactType, ContextEnvelopeInput, Precondition, Constraint

    artifact_type = accumulated_context.get("artifact_type", "other")
    objective = accumulated_context.get("objective", "")

    context_envelope = None
    if "context_envelope" in accumulated_context:
        context_envelope = ContextEnvelopeInput(**accumulated_context["context_envelope"])

    situation = accumulated_context.get("situation")
    observations = accumulated_context.get("observations", [])
    triggers = accumulated_context.get("triggers", [])

    preconditions = []
    for p in accumulated_context.get("preconditions", []):
        preconditions.append(Precondition(**p))

    constraints = []
    for c in accumulated_context.get("constraints", []):
        constraints.append(Constraint(**c))

    return DecisionArtifact(
        artifact_type=ArtifactType(artifact_type),
        objective=objective,
        context_envelope=context_envelope,
        situation=situation,
        observations=observations,
        preconditions=preconditions,
        constraints=constraints,
        triggers=triggers,
    )
