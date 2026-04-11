"""LLMProvider protocol and implementations."""

from __future__ import annotations

import json
import logging
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from app.models.codex_objects import CodexObject
from app.models.schemas import DecisionArtifact

logger = logging.getLogger(__name__)


class EvaluationResult(BaseModel):
    confidence: float
    evaluation: str  # "supported", "conditional", "abstain"
    doctrine_coverage: str | None = None  # "direct", "analogous", "partial"
    coverage_basis: list[str] = []
    coverage_gaps: list[str] = []

    guidance_actions: list[dict] = []

    unmet_preconditions: list[str] = []
    required_observations: list[str] = []
    active_tradeoffs: list[dict] = []
    constraint_notes: list[str] = []

    clarification_questions: list[dict] = []
    context_summary: str = ""

    abstain_reason: str | None = None
    reasoning_trace: str = ""


@runtime_checkable
class LLMProvider(Protocol):
    async def evaluate(
        self, artifact: DecisionArtifact, codex_objects: list[CodexObject], accumulated_context: dict
    ) -> EvaluationResult:
        ...


class MockLLMProvider:
    """Deterministic mock that evaluates based on artifact completeness and CODEX object matching."""

    async def evaluate(
        self, artifact: DecisionArtifact, codex_objects: list[CodexObject], accumulated_context: dict
    ) -> EvaluationResult:
        if not codex_objects:
            return EvaluationResult(
                confidence=0.1,
                evaluation="abstain",
                abstain_reason="no_doctrinal_coverage",
                reasoning_trace="No relevant CODEX objects found for the given artifact.",
            )

        completeness = self._assess_completeness(artifact, accumulated_context)
        primary_codex = codex_objects[0]

        has_prior_clarification = "clarification_responses" in accumulated_context
        if completeness < 0.55 and not has_prior_clarification:
            return EvaluationResult(
                confidence=completeness * 0.5,
                evaluation="abstain",
                abstain_reason="insufficient_information",
                context_summary=self._summarize_context(artifact, accumulated_context),
                clarification_questions=self._generate_questions(artifact, codex_objects, accumulated_context),
                reasoning_trace=f"Artifact completeness too low ({completeness:.2f}) to provide confident guidance. Requesting clarification.",
            )

        precondition_issues = self._check_preconditions(artifact, codex_objects, accumulated_context)
        tradeoffs = self._identify_tradeoffs(artifact, codex_objects)
        # Only check observations against the primary CODEX object
        missing_observations = self._check_observations(artifact, [primary_codex], accumulated_context)

        has_issues = bool(precondition_issues or missing_observations)
        confidence = completeness * (0.75 if has_issues else 1.0)

        guidance_actions = self._build_guidance(artifact, codex_objects)
        coverage = self._assess_coverage(artifact, codex_objects)

        if has_issues:
            return EvaluationResult(
                confidence=confidence,
                evaluation="conditional",
                doctrine_coverage=coverage["type"],
                coverage_basis=coverage.get("basis", []),
                coverage_gaps=coverage.get("gaps", []),
                guidance_actions=guidance_actions,
                unmet_preconditions=precondition_issues,
                required_observations=missing_observations,
                active_tradeoffs=tradeoffs,
                constraint_notes=[c for c in primary_codex.constraints],
                reasoning_trace=f"CODEX objects matched but conditions exist. Confidence: {confidence:.2f}.",
            )

        return EvaluationResult(
            confidence=confidence,
            evaluation="supported",
            doctrine_coverage=coverage["type"],
            coverage_basis=coverage.get("basis", []),
            guidance_actions=guidance_actions,
            constraint_notes=[c for c in primary_codex.constraints],
            reasoning_trace=f"Artifact fully supported by CODEX objects. Confidence: {confidence:.2f}.",
        )

    def _assess_completeness(self, artifact: DecisionArtifact, accumulated_context: dict) -> float:
        score = 0.3  # base score for having artifact_type + objective
        if artifact.context_envelope:
            score += 0.1
        if artifact.situation:
            score += 0.15
        if artifact.proposed_actions:
            score += 0.15
        if artifact.preconditions:
            score += 0.1
        if artifact.constraints:
            score += 0.05
        if artifact.observations:
            score += 0.1
        if artifact.triggers:
            score += 0.05
        if accumulated_context:
            score += min(0.15, len(accumulated_context) * 0.05)
        return min(score, 1.0)

    def _check_preconditions(
        self, artifact: DecisionArtifact, codex_objects: list[CodexObject], accumulated_context: dict
    ) -> list[str]:
        issues = []
        for pc in artifact.preconditions:
            if pc.status == "unknown" or pc.status is False:
                issues.append(f"{pc.condition}_unverified")

        clarification_answers = accumulated_context.get("clarification_responses", {})
        issues = [i for i in issues if i.replace("_unverified", "") not in str(clarification_answers)]
        return issues

    def _check_observations(
        self, artifact: DecisionArtifact, codex_objects: list[CodexObject], accumulated_context: dict
    ) -> list[str]:
        required = set()
        for obj in codex_objects:
            required.update(obj.required_observations)

        provided = set(o.lower() for o in artifact.observations)
        ctx_obs = set(str(v).lower() for v in accumulated_context.get("observations", []))
        provided.update(ctx_obs)

        missing = []
        for req in required:
            if not any(req.lower() in p for p in provided):
                missing.append(req)
        return missing

    def _identify_tradeoffs(
        self, artifact: DecisionArtifact, codex_objects: list[CodexObject]
    ) -> list[dict]:
        tradeoffs = []
        proposed = {a.action.lower() for a in artifact.proposed_actions}
        for obj in codex_objects:
            for t in obj.tradeoffs:
                if t.action.lower() in proposed or not proposed:
                    tradeoffs.append({
                        "tradeoff": t.action,
                        "degradation": t.degradation,
                        "compensation": t.compensation,
                    })
        return tradeoffs

    def _build_guidance(
        self, artifact: DecisionArtifact, codex_objects: list[CodexObject]
    ) -> list[dict]:
        actions = []
        seq = 1
        # Use top 2 most relevant CODEX objects for guidance
        for obj in codex_objects[:2]:
            for allowed in obj.allowed_actions:
                actions.append({
                    "sequence": seq,
                    "action": allowed.action,
                    "parameters": allowed.parameters,
                    "conditions": [],
                    "constraints": obj.constraints,
                })
                seq += 1
        return actions

    def _assess_coverage(
        self, artifact: DecisionArtifact, codex_objects: list[CodexObject]
    ) -> dict:
        if not codex_objects:
            return {"type": None}

        best = codex_objects[0]
        ce_match = False
        if artifact.context_envelope and best.context_envelope:
            ce = artifact.context_envelope
            bc = best.context_envelope
            ce_match = (
                ce.mission_type and bc.mission_type
                and ce.mission_type.lower() == bc.mission_type.lower()
            )

        if ce_match:
            return {"type": "direct", "basis": best.provenance}

        if codex_objects:
            return {
                "type": "analogous",
                "basis": best.provenance,
                "gaps": [],
            }

        return {"type": "partial", "basis": best.provenance, "gaps": ["limited_coverage"]}

    def _summarize_context(self, artifact: DecisionArtifact, accumulated_context: dict) -> str:
        parts = [f"Request type: {artifact.artifact_type.value}"]
        parts.append(f"Objective: {artifact.objective}")
        if artifact.situation:
            for key in artifact.situation:
                parts.append(f"{key}: provided")
        return ". ".join(parts)

    def _generate_questions(
        self, artifact: DecisionArtifact, codex_objects: list[CodexObject], accumulated_context: dict
    ) -> list[dict]:
        questions = []
        q_id = 1

        if not artifact.situation or "friendly_forces" not in artifact.situation:
            questions.append({
                "id": f"q{q_id}",
                "question": "What is the composition and strength of friendly forces?",
                "reason_needed": "Force composition determines viable doctrinal options",
                "expected_format": "unit_composition",
            })
            q_id += 1

        if not artifact.situation or "enemy_forces" not in artifact.situation:
            questions.append({
                "id": f"q{q_id}",
                "question": "What is the known or estimated enemy composition and disposition?",
                "reason_needed": "Enemy assessment drives course of action development",
                "expected_format": "enemy_assessment",
            })
            q_id += 1

        if not artifact.context_envelope:
            questions.append({
                "id": f"q{q_id}",
                "question": "What echelon, phase, and mission type does this request apply to?",
                "reason_needed": "Context envelope scopes which doctrinal reasoning applies",
                "expected_format": "context_envelope",
            })
            q_id += 1

        if not artifact.constraints:
            questions.append({
                "id": f"q{q_id}",
                "question": "Are there ROE or other operational constraints in effect?",
                "reason_needed": "Constraints determine permissible actions and fires",
                "expected_format": "constraint_list",
            })
            q_id += 1

        for obj in codex_objects[:2]:
            for obs in obj.required_observations:
                if obs.lower() not in {o.lower() for o in artifact.observations}:
                    questions.append({
                        "id": f"q{q_id}",
                        "question": f"Has the following been observed/confirmed: {obs.replace('_', ' ')}?",
                        "reason_needed": f"Required observation for doctrinal evaluation",
                        "expected_format": "boolean_with_detail",
                    })
                    q_id += 1

        return questions[:5]


class OpenAILLMProvider:
    """Production LLM provider wrapping the OpenAI API."""

    def __init__(self, api_key: str, model: str = "gpt-4o"):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def evaluate(
        self, artifact: DecisionArtifact, codex_objects: list[CodexObject], accumulated_context: dict
    ) -> EvaluationResult:
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(artifact, codex_objects, accumulated_context)

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            raw = json.loads(response.choices[0].message.content)
            return EvaluationResult(**raw)
        except Exception as e:
            logger.error(f"OpenAI evaluation failed: {e}")
            return EvaluationResult(
                confidence=0.0,
                evaluation="abstain",
                abstain_reason="insufficient_information",
                reasoning_trace=f"LLM evaluation failed: {str(e)}",
            )

    def _build_system_prompt(self) -> str:
        return """You are a CODEX/WARBRAIN doctrinal evaluation engine. You evaluate decision artifacts against CODEX objects (compiled doctrinal reasoning patterns).

Given a decision artifact and relevant CODEX objects, you must:
1. Validate the artifact's preconditions against CODEX required preconditions
2. Check proposed actions against CODEX allowed actions
3. Identify active tradeoffs from CODEX tradeoff mappings
4. Check observations against CODEX required observations
5. Assess constraints for conflicts

Return a JSON object with these fields:
- confidence: float 0-1
- evaluation: "supported" | "conditional" | "abstain"
- doctrine_coverage: "direct" | "analogous" | "partial" | null
- coverage_basis: list of doctrinal sources
- coverage_gaps: list of uncovered areas
- guidance_actions: list of {sequence, action, parameters, conditions, constraints}
- unmet_preconditions: list of unmet/unverified preconditions
- required_observations: list of missing required observations
- active_tradeoffs: list of {tradeoff, degradation, compensation}
- constraint_notes: list of applicable constraints
- clarification_questions: list of {id, question, reason_needed, expected_format} (only if abstaining)
- context_summary: string summary of understood context (only if abstaining)
- abstain_reason: "insufficient_information" | "no_doctrinal_coverage" | null
- reasoning_trace: string explaining your reasoning"""

    def _build_user_prompt(
        self, artifact: DecisionArtifact, codex_objects: list[CodexObject], accumulated_context: dict
    ) -> str:
        parts = ["## Decision Artifact", artifact.model_dump_json(indent=2)]
        parts.append("\n## Relevant CODEX Objects")
        for obj in codex_objects:
            parts.append(obj.model_dump_json(indent=2))
        if accumulated_context:
            parts.append("\n## Accumulated Session Context")
            parts.append(json.dumps(accumulated_context, indent=2))
        return "\n\n".join(parts)
