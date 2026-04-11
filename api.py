"""FastAPI application with retrieval, CODEX, and health endpoints."""
import sys
import json
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent / "codex"))

app = FastAPI(
    title="KD Platform Prototype",
    version="0.1.0",
    description="End-to-end Knowledge Domain platform demonstrating ADC, semantic lifting, hybrid retrieval, and CODEX evaluation.",
)


class RetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4096)
    filters: Optional[dict] = None
    top_k: int = Field(default=10, ge=1, le=100)
    alpha: float = Field(default=0.7, ge=0.0, le=1.0)
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class RetrieveResponse(BaseModel):
    query: str
    results: list[dict]
    count: int


@app.get("/health")
def health():
    return {"status": "ok", "service": "kd-platform", "version": "0.1.0"}


@app.post("/kd/doctrine/retrieve", response_model=RetrieveResponse)
def retrieve_endpoint(req: RetrieveRequest):
    from src.retrieve import retrieve
    results = retrieve(
        query=req.query,
        top_k=req.top_k,
        alpha=req.alpha,
        filters=req.filters,
        min_confidence=req.min_confidence,
    )
    serialized = []
    for r in results:
        row = dict(r)
        for key in row:
            if hasattr(row[key], "isoformat"):
                row[key] = row[key].isoformat()
            elif isinstance(row[key], bytes):
                row[key] = row[key].decode()
        serialized.append(row)

    return RetrieveResponse(query=req.query, results=serialized, count=len(serialized))


class CodexRequest(BaseModel):
    """Simplified CODEX evaluation request for the demo."""
    objective: str
    mission_type: str = ""
    echelon: str = ""
    phase: str = ""
    domain: str = "land"
    observations: list[str] = []
    proposed_actions: list[str] = []
    triggers: list[str] = []


@app.post("/kd/doctrine/codex")
def codex_endpoint(req: CodexRequest):
    """Evaluate a decision artifact against compiled doctrine via the CODEX rule engine."""
    from src.codex_retriever import retrieve_codex_objects

    context = {
        "mission_type": req.mission_type,
        "echelon": req.echelon,
        "phase": req.phase,
        "domain": req.domain,
        "objective": req.objective,
        "triggers": req.triggers,
    }

    matched_objects = retrieve_codex_objects(context, top_k=3)

    if not matched_objects:
        return {
            "evaluation": "ABSTAIN",
            "abstain_reason": "no_doctrinal_coverage",
            "message": "No compiled doctrine covers this combination of mission type, echelon, and phase.",
            "codex_objects_searched": len(json.load(open("data/compiled_codex_objects.json"))),
        }

    primary = matched_objects[0]
    ce = primary.get("context_envelope", {})

    # Determine coverage type
    exact_fields = sum(1 for f in ["mission_type", "echelon", "phase", "domain"]
                       if context.get(f) and ce.get(f) and context[f].lower() in ce[f].lower())
    total_fields = sum(1 for f in ["mission_type", "echelon", "phase", "domain"] if context.get(f))

    if total_fields > 0 and exact_fields == total_fields:
        coverage = "DIRECT"
    elif exact_fields >= 1:
        coverage = "ANALOGOUS"
    else:
        coverage = "PARTIAL"

    # Check causal chains
    trust_factors = []
    caution_factors = []
    evidence_tokens = set()
    for obs in req.observations:
        evidence_tokens.update(obs.lower().split())
    for act in req.proposed_actions:
        evidence_tokens.update(act.lower().split())

    for chain in primary.get("causal_chains", []):
        chain_satisfied = True
        for link in chain.get("links", []):
            condition_tokens = set(link.get("condition", "").lower().split())
            overlap = condition_tokens & evidence_tokens
            if len(overlap) < max(1, len(condition_tokens) * 0.3):
                chain_satisfied = False
                caution_factors.append(
                    f"Causal chain '{chain.get('pattern_name', '?')}' broken at "
                    f"'{link.get('condition', '?')}': condition not evidenced in artifact"
                )
                break
        if chain_satisfied:
            trust_factors.append(
                f"Causal chain '{chain.get('pattern_name', '?')}' fully satisfied"
            )

    # Determine evaluation outcome
    if caution_factors:
        evaluation = "CONDITIONAL"
        recommendation = "Review caution factors before execution."
    elif not trust_factors:
        evaluation = "CONDITIONAL"
        recommendation = "Insufficient evidence to fully validate. Provide more observations."
    else:
        evaluation = "SUPPORTED"
        recommendation = "All evaluated causal chains satisfied."

    return {
        "evaluation": evaluation,
        "doctrine_coverage": coverage,
        "coverage_basis": [primary["codex_id"]],
        "trust_factors": trust_factors,
        "caution_factors": caution_factors,
        "recommendation": recommendation,
        "guidance_actions": [a.get("action", "") for a in primary.get("allowed_actions", [])[:5]],
        "constraints": primary.get("constraints", [])[:5],
        "codex_object_used": primary.get("codex_id"),
        "context_envelope_match": {
            "requested": context,
            "matched": ce,
            "coverage_type": coverage,
        },
    }


@app.get("/kd/doctrine/stats")
def stats_endpoint():
    from src.db import get_connection
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) as total FROM kd_doctrine")
            total = cur.fetchone()["total"]
            cur.execute("SELECT modality, count(*) as cnt FROM kd_doctrine GROUP BY modality ORDER BY cnt DESC")
            modality_dist = {r["modality"]: r["cnt"] for r in cur.fetchall()}
            cur.execute("SELECT count(*) as lifted FROM kd_doctrine WHERE lift_model_version IS NOT NULL")
            lifted = cur.fetchone()["lifted"]
    finally:
        conn.close()
    return {"total_chunks": total, "lifted_chunks": lifted, "modality_distribution": modality_dist}
