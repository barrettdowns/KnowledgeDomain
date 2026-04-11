"""CODEX object schema -- the unit of compiled doctrinal reasoning.

Includes both explicit doctrine (actions, constraints, triggers) and
implicit knowledge (causal chains extracted at ingestion time).
"""

from pydantic import BaseModel


class ContextEnvelope(BaseModel):
    echelon: str | None = None
    phase: str | None = None
    mission_type: str | None = None
    domain: str | None = None


class AllowedAction(BaseModel):
    action: str
    parameters: dict[str, str] = {}
    intended_effects: list[str] = []


class Tradeoff(BaseModel):
    action: str
    degradation: str
    compensation: str


class CausalLink(BaseModel):
    """Single link in a causal reasoning chain.

    Represents: IF <condition> THEN <effect> BECAUSE <mechanism> UNLESS <exception>
    Extracted from doctrine by LLM at ingestion time and validated by SMEs.
    """
    condition: str
    effect: str
    mechanism: str
    exception: str | None = None


class CausalChain(BaseModel):
    """A sequence of causal links encoding implicit doctrinal reasoning.

    Captures the WHY behind allowed actions -- the doctrinal logic that
    a SME would apply but that isn't stated as explicit instruction.
    """
    chain_id: str
    pattern_name: str
    links: list[CausalLink]
    cross_references: list[str] = []
    provenance: list[str] = []


class CodexObject(BaseModel):
    codex_id: str
    context_envelope: ContextEnvelope = ContextEnvelope()
    triggers: list[str] = []
    required_observations: list[str] = []
    allowed_actions: list[AllowedAction] = []
    intended_effects: list[str] = []
    constraints: list[str] = []
    tradeoffs: list[Tradeoff] = []
    causal_chains: list[CausalChain] = []
    measures: list[str] = []
    provenance: list[str] = []
