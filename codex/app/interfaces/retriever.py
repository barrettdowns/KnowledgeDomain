"""CodexRetriever protocol and mock implementation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.models.codex_objects import CodexObject
from app.models.schemas import DecisionArtifact


@runtime_checkable
class CodexRetriever(Protocol):
    async def retrieve(
        self, artifact: DecisionArtifact, top_k: int = 10
    ) -> list[CodexObject]:
        ...


class MockCodexRetriever:
    """Returns sample CODEX objects from a JSON file for MVP demo."""

    def __init__(self, data_path: str | None = None):
        if data_path is None:
            data_path = str(Path(__file__).parent.parent.parent / "data" / "sample_codex_objects.json")
        self._data_path = data_path
        self._objects: list[CodexObject] = []

    async def _load(self) -> None:
        if self._objects:
            return
        path = Path(self._data_path)
        if path.exists():
            with open(path, "r") as f:
                raw = json.load(f)
            self._objects = [CodexObject(**obj) for obj in raw]

    async def retrieve(
        self, artifact: DecisionArtifact, top_k: int = 10
    ) -> list[CodexObject]:
        await self._load()
        if not self._objects:
            return []

        scored: list[tuple[float, CodexObject]] = []
        for obj in self._objects:
            score = self._relevance_score(artifact, obj)
            if score >= 3.0:
                scored.append((score, obj))

        scored.sort(key=lambda x: x[0], reverse=True)

        if not scored:
            return []

        top_score = scored[0][0]
        relevant = [(s, obj) for s, obj in scored if s >= top_score * 0.5]
        return [obj for _, obj in relevant[:top_k]]

    def _relevance_score(self, artifact: DecisionArtifact, obj: CodexObject) -> float:
        """Simple keyword/overlap scoring for the mock retriever."""
        score = 0.0

        if artifact.context_envelope and obj.context_envelope:
            ce = artifact.context_envelope
            oc = obj.context_envelope
            if ce.echelon and oc.echelon and ce.echelon.lower() == oc.echelon.lower():
                score += 2.0
            if ce.phase and oc.phase and ce.phase.lower() == oc.phase.lower():
                score += 2.0
            if ce.mission_type and oc.mission_type and ce.mission_type.lower() == oc.mission_type.lower():
                score += 3.0
            if ce.domain and oc.domain and ce.domain.lower() == oc.domain.lower():
                score += 1.0

        artifact_triggers = {t.lower() for t in artifact.triggers}
        obj_triggers = {t.lower() for t in obj.triggers}
        trigger_overlap = artifact_triggers & obj_triggers
        score += len(trigger_overlap) * 2.0

        objective_words = set(artifact.objective.lower().split())
        action_words = set()
        for a in obj.allowed_actions:
            action_words.update(a.action.lower().replace("_", " ").split())
        for e in obj.intended_effects:
            action_words.update(e.lower().replace("_", " ").split())
        keyword_overlap = objective_words & action_words
        score += len(keyword_overlap) * 0.5

        return score
