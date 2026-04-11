"""Real CodexRetriever backed by compiled CODEX objects from the KD pipeline.

Implements the CodexRetriever Protocol from the CODEX conversation layer,
replacing MockCodexRetriever with objects compiled from real ADP 3-0 doctrine.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

COMPILED_PATH = Path(__file__).parent.parent / "data" / "compiled_codex_objects.json"


def _load_objects():
    if not COMPILED_PATH.exists():
        logger.warning(f"Compiled objects not found at {COMPILED_PATH}")
        return []
    return json.load(open(COMPILED_PATH))


def _score_relevance(obj: dict, context: dict) -> float:
    """Score a CODEX object against artifact context using field alignment."""
    score = 0.0
    ce = obj.get("context_envelope", {})

    if context.get("mission_type") and ce.get("mission_type"):
        if context["mission_type"].lower() in ce["mission_type"].lower():
            score += 3.0
        elif any(w in ce["mission_type"].lower() for w in context["mission_type"].lower().split("_")):
            score += 1.5

    if context.get("echelon") and ce.get("echelon"):
        if context["echelon"].lower() in ce["echelon"].lower():
            score += 2.0

    if context.get("phase") and ce.get("phase"):
        if context["phase"].lower() in ce["phase"].lower():
            score += 2.0

    if context.get("domain") and ce.get("domain"):
        if context["domain"].lower() in ce["domain"].lower():
            score += 1.0

    # Trigger overlap
    artifact_triggers = set(t.lower() for t in context.get("triggers", []))
    obj_triggers = set(t.lower() for t in obj.get("triggers", []))
    overlap = artifact_triggers & obj_triggers
    score += len(overlap) * 2.0

    # Keyword overlap between objective and actions/effects
    objective_words = set(context.get("objective", "").lower().split())
    obj_keywords = set()
    for action in obj.get("allowed_actions", []):
        obj_keywords.update(action.get("action", "").lower().split())
        for effect in action.get("intended_effects", []):
            obj_keywords.update(effect.lower().split())
    keyword_overlap = objective_words & obj_keywords - {"the", "a", "an", "and", "or", "to", "of", "in", "for"}
    score += len(keyword_overlap) * 0.5

    return score


def retrieve_codex_objects(context: dict, top_k: int = 5) -> list[dict]:
    """Retrieve relevant CODEX objects for a given artifact context.

    Args:
        context: dict with mission_type, echelon, phase, domain, triggers, objective
        top_k: max objects to return

    Returns:
        List of CODEX objects sorted by relevance score
    """
    objects = _load_objects()
    if not objects:
        return []

    scored = [(obj, _score_relevance(obj, context)) for obj in objects]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Filter to minimum threshold
    min_score = 1.0
    results = [(obj, score) for obj, score in scored if score >= min_score]

    if not results:
        logger.info("No CODEX objects met minimum relevance threshold")
        return []

    # Return top-k within 50% of top score
    top_score = results[0][1]
    filtered = [obj for obj, score in results if score >= top_score * 0.5]

    logger.info(f"Retrieved {len(filtered[:top_k])} CODEX objects (top score: {top_score:.1f})")
    return filtered[:top_k]
