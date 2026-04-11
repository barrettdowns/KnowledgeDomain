"""Deterministic CODEX Rule Engine.

Evaluates decision artifacts against CODEX objects using structural
comparison, set operations, causal chain traversal, and threshold logic.
Same input always produces the same output. No LLM in the critical path.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.models.codex_objects import CausalChain, CodexObject
from app.models.schemas import DecisionArtifact


class CausalChainResult(BaseModel):
    chain_id: str
    pattern_name: str
    satisfied: bool
    active_links: list[str] = []
    broken_at: str | None = None
    broken_reason: str | None = None
    exception_triggered: str | None = None
    provenance: list[str] = []


class CoherenceCheckResult(BaseModel):
    """Result of a single doctrinal coherence rule.

    Coherence rules evaluate whether the overall picture -- the artifact
    plus the guidance -- aligns with how the Army reasons at a level above
    individual actions and constraints.  These are cross-cutting principles
    (mass, security, synchronization, sequencing norms) that apply regardless
    of which CODEX objects are matched.

    Each rule is authored by SMEs and executed deterministically.
    """
    rule_id: str
    rule_name: str
    passed: bool
    detail: str
    category: str  # "warfighting_function", "sequencing", "principle", "anti_pattern"


class MetaEvaluationDetail(BaseModel):
    trust_factors: list[str] = []
    caution_factors: list[str] = []
    doctrinal_grounding: str = "none"
    novel_situation: bool = False
    response_completeness: float = 0.0
    recommendation: str = ""
    coherence_checks: list[CoherenceCheckResult] = []


class RuleEngineResult(BaseModel):
    confidence: float
    evaluation: str
    doctrine_coverage: str | None = None
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

    causal_chain_results: list[CausalChainResult] = []
    meta: MetaEvaluationDetail = MetaEvaluationDetail()
    rule_trace: list[str] = []


class CodexRuleEngine:
    """Deterministic evaluation engine.

    Every method is a pure function of its inputs. No randomness,
    no external API calls, no side effects. Fully auditable.
    """

    async def evaluate(
        self,
        artifact: DecisionArtifact,
        codex_objects: list[CodexObject],
        accumulated_context: dict,
    ) -> RuleEngineResult:
        trace: list[str] = []

        # --- Gate 0: No CODEX match ---
        if not codex_objects:
            trace.append("GATE_0: No CODEX objects retrieved")
            nearest = self._find_nearest_partial(artifact, codex_objects)
            meta = self._build_meta_no_coverage(artifact, trace)
            return RuleEngineResult(
                confidence=0.05,
                evaluation="abstain",
                abstain_reason="no_doctrinal_coverage",
                reasoning_trace="No CODEX objects matched the artifact. "
                    + (f"Nearest partial context: {nearest}" if nearest else "No partial matches available."),
                meta=meta,
                rule_trace=trace,
            )

        primary = codex_objects[0]
        trace.append(f"PRIMARY_CODEX: {primary.codex_id}")

        # --- Step 1: Completeness ---
        completeness = self._assess_completeness(artifact, accumulated_context)
        trace.append(f"COMPLETENESS: {completeness:.2f}")

        # --- Gate 1: Too sparse to evaluate ---
        has_prior_clarification = "clarification_responses" in accumulated_context
        if completeness < 0.55 and not has_prior_clarification:
            trace.append("GATE_1: Completeness below threshold, no prior clarification")
            questions = self._generate_questions(artifact, codex_objects, accumulated_context)
            meta = self._build_meta_sparse(artifact, completeness, codex_objects, trace)
            return RuleEngineResult(
                confidence=completeness * 0.5,
                evaluation="abstain",
                abstain_reason="insufficient_information",
                context_summary=self._summarize_context(artifact, accumulated_context),
                clarification_questions=questions,
                reasoning_trace=f"Artifact completeness {completeness:.2f} below evaluation threshold (0.55).",
                meta=meta,
                rule_trace=trace,
            )

        # --- Step 2: Structural evaluation ---
        precondition_issues = self._check_preconditions(artifact, codex_objects, accumulated_context)
        trace.append(f"PRECONDITIONS_UNMET: {precondition_issues}")

        missing_observations = self._check_observations(artifact, primary, accumulated_context)
        trace.append(f"OBSERVATIONS_MISSING: {missing_observations}")

        action_validation = self._validate_actions(artifact, codex_objects)
        trace.append(f"ACTION_VALIDATION: {action_validation}")

        constraint_conflicts = self._check_constraints(artifact, codex_objects)
        trace.append(f"CONSTRAINT_CONFLICTS: {constraint_conflicts}")

        tradeoffs = self._identify_tradeoffs(artifact, codex_objects)
        trace.append(f"ACTIVE_TRADEOFFS: {len(tradeoffs)}")

        # --- Step 3: Causal chain evaluation (implicit knowledge) ---
        chain_results = self._evaluate_causal_chains(artifact, codex_objects, accumulated_context)
        trace.append(f"CAUSAL_CHAINS_EVALUATED: {len(chain_results)}")
        for cr in chain_results:
            status = "SATISFIED" if cr.satisfied else f"BROKEN at {cr.broken_at}"
            trace.append(f"  CHAIN {cr.chain_id} ({cr.pattern_name}): {status}")

        # --- Step 4: Doctrinal coherence (does this make sense?) ---
        coherence_results = self._check_doctrinal_coherence(
            artifact, codex_objects, action_validation, chain_results,
        )
        trace.append(f"COHERENCE_CHECKS: {len(coherence_results)} rules evaluated")
        coherence_failures = [c for c in coherence_results if not c.passed]
        trace.append(f"COHERENCE_FAILURES: {len(coherence_failures)}")
        for cr in coherence_results:
            status = "PASS" if cr.passed else "FAIL"
            trace.append(f"  {cr.rule_id} ({cr.rule_name}): {status}")

        # --- Step 5: Coverage assessment ---
        coverage = self._assess_coverage(artifact, codex_objects)
        trace.append(f"COVERAGE: {coverage['type']}")

        # --- Step 6: Build guidance ---
        guidance = self._build_guidance(artifact, codex_objects, action_validation)

        # --- Step 7: Compute confidence and determine outcome ---
        has_issues = bool(precondition_issues or missing_observations or constraint_conflicts)
        broken_chains = [cr for cr in chain_results if not cr.satisfied]

        confidence = completeness
        if has_issues:
            confidence *= 0.75
        if broken_chains:
            confidence *= 0.85
        if coherence_failures:
            confidence *= 0.9
        if coverage["type"] == "analogous":
            confidence *= 0.9
        elif coverage["type"] == "partial":
            confidence *= 0.7

        trace.append(f"FINAL_CONFIDENCE: {confidence:.2f}")

        all_constraints = list(primary.constraints)
        for conflict in constraint_conflicts:
            if conflict not in all_constraints:
                all_constraints.append(conflict)

        # --- Step 8: Meta-evaluation ---
        meta = self._build_meta(
            artifact, codex_objects, coverage, completeness, confidence,
            precondition_issues, missing_observations, constraint_conflicts,
            tradeoffs, chain_results, action_validation, coherence_results, trace,
        )

        if has_issues or broken_chains:
            trace.append("OUTCOME: conditional")
            return RuleEngineResult(
                confidence=confidence,
                evaluation="conditional",
                doctrine_coverage=coverage["type"],
                coverage_basis=coverage.get("basis", []),
                coverage_gaps=coverage.get("gaps", []),
                guidance_actions=guidance,
                unmet_preconditions=precondition_issues,
                required_observations=missing_observations,
                active_tradeoffs=tradeoffs,
                constraint_notes=all_constraints,
                causal_chain_results=chain_results,
                meta=meta,
                reasoning_trace=f"CODEX objects matched with conditions. Confidence: {confidence:.2f}.",
                rule_trace=trace,
            )

        trace.append("OUTCOME: supported")
        return RuleEngineResult(
            confidence=confidence,
            evaluation="supported",
            doctrine_coverage=coverage["type"],
            coverage_basis=coverage.get("basis", []),
            guidance_actions=guidance,
            constraint_notes=all_constraints,
            causal_chain_results=chain_results,
            meta=meta,
            reasoning_trace=f"Artifact fully supported by CODEX objects. Confidence: {confidence:.2f}.",
            rule_trace=trace,
        )

    # ================================================================
    # Structural evaluation methods
    # ================================================================

    def _assess_completeness(self, artifact: DecisionArtifact, accumulated_context: dict) -> float:
        score = 0.3
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
        self, artifact: DecisionArtifact, primary: CodexObject, accumulated_context: dict
    ) -> list[str]:
        required = set(primary.required_observations)
        provided = set(o.lower() for o in artifact.observations)
        ctx_obs = set(str(v).lower() for v in accumulated_context.get("observations", []))
        provided.update(ctx_obs)

        missing = []
        for req in required:
            if not any(req.lower() in p for p in provided):
                missing.append(req)
        return missing

    def _validate_actions(
        self, artifact: DecisionArtifact, codex_objects: list[CodexObject]
    ) -> dict:
        """Check proposed actions against CODEX allowed actions."""
        allowed = set()
        for obj in codex_objects:
            for a in obj.allowed_actions:
                allowed.add(a.action.lower())

        proposed = set()
        aligned = []
        unrecognized = []
        for pa in artifact.proposed_actions:
            proposed.add(pa.action.lower())
            if pa.action.lower() in allowed:
                aligned.append(pa.action)
            else:
                unrecognized.append(pa.action)

        not_proposed = [a for a in allowed if a not in proposed] if proposed else []

        return {
            "aligned": aligned,
            "unrecognized": unrecognized,
            "available_not_proposed": not_proposed,
        }

    def _check_constraints(
        self, artifact: DecisionArtifact, codex_objects: list[CodexObject]
    ) -> list[str]:
        """Identify constraint conflicts between artifact and CODEX objects."""
        conflicts = []
        codex_constraints = set()
        for obj in codex_objects:
            codex_constraints.update(c.lower() for c in obj.constraints)

        for pa in artifact.proposed_actions:
            for pc in pa.constraints:
                if pc.lower() in codex_constraints:
                    continue

        artifact_constraint_values = {c.value.lower() for c in artifact.constraints}
        for cc in codex_constraints:
            key = cc.replace("_", " ")
            if any(key in acv for acv in artifact_constraint_values):
                continue

        return conflicts

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

    # ================================================================
    # Causal chain evaluation (implicit knowledge)
    # ================================================================

    def _evaluate_causal_chains(
        self,
        artifact: DecisionArtifact,
        codex_objects: list[CodexObject],
        accumulated_context: dict,
    ) -> list[CausalChainResult]:
        results = []
        situation_tokens = self._extract_situation_tokens(artifact, accumulated_context)

        for obj in codex_objects[:2]:
            for chain in obj.causal_chains:
                result = self._evaluate_single_chain(chain, situation_tokens, artifact)
                results.append(result)

        return results

    def _evaluate_single_chain(
        self, chain: CausalChain, situation_tokens: set[str], artifact: DecisionArtifact
    ) -> CausalChainResult:
        active_links = []
        proposed_action_phrases = set()
        for a in artifact.proposed_actions:
            proposed_action_phrases.update(a.action.lower().replace("_", " ").split())
            for ie in a.intended_effects:
                proposed_action_phrases.update(ie.lower().replace("_", " ").split())

        all_evidence = set(situation_tokens) | proposed_action_phrases
        # Effects from satisfied links propagate as evidence for subsequent conditions
        propagated_effects: set[str] = set()

        for link in chain.links:
            condition_tokens = self._phrase_tokens(link.condition)
            meaningful_condition_tokens = condition_tokens - self._stop_words()
            evidence_pool = all_evidence | propagated_effects
            meaningful_overlap = meaningful_condition_tokens & evidence_pool
            condition_met = (
                len(meaningful_overlap) >= max(1, len(meaningful_condition_tokens) * 0.4)
            )

            if link.exception:
                exception_tokens = self._phrase_tokens(link.exception)
                meaningful_exception = exception_tokens - self._stop_words()
                exception_overlap = meaningful_exception & evidence_pool
                exception_active = (
                    len(meaningful_exception) > 0
                    and len(exception_overlap) >= max(2, len(meaningful_exception) * 0.6)
                )
                if exception_active:
                    return CausalChainResult(
                        chain_id=chain.chain_id,
                        pattern_name=chain.pattern_name,
                        satisfied=False,
                        active_links=active_links,
                        broken_at=link.condition,
                        broken_reason=f"Exception condition active: {link.exception}",
                        exception_triggered=link.exception,
                        provenance=chain.provenance,
                    )

            if condition_met:
                active_links.append(f"{link.condition} -> {link.effect}")
                effect_tokens = self._phrase_tokens(link.effect)
                propagated_effects.update(effect_tokens - self._stop_words())
            else:
                return CausalChainResult(
                    chain_id=chain.chain_id,
                    pattern_name=chain.pattern_name,
                    satisfied=False,
                    active_links=active_links,
                    broken_at=link.condition,
                    broken_reason=f"Condition not evidenced in artifact: {link.condition}",
                    provenance=chain.provenance,
                )

        return CausalChainResult(
            chain_id=chain.chain_id,
            pattern_name=chain.pattern_name,
            satisfied=True,
            active_links=active_links,
            provenance=chain.provenance,
        )

    def _extract_situation_tokens(
        self, artifact: DecisionArtifact, accumulated_context: dict
    ) -> set[str]:
        tokens: set[str] = set()
        if artifact.situation:
            tokens.update(self._flatten_to_tokens(artifact.situation))
        if artifact.context_envelope:
            for val in artifact.context_envelope.model_dump(exclude_none=True).values():
                tokens.update(str(val).lower().replace("_", " ").split())
        for t in artifact.triggers:
            tokens.update(t.lower().replace("_", " ").split())
        for obs in artifact.observations:
            tokens.update(obs.lower().replace("_", " ").split())
        if "situation" in accumulated_context:
            tokens.update(self._flatten_to_tokens(accumulated_context["situation"]))
        return tokens

    def _phrase_tokens(self, phrase: str) -> set[str]:
        return set(phrase.lower().replace("_", " ").split())

    def _stop_words(self) -> set[str]:
        return {
            "a", "an", "the", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "shall", "can",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "as", "into", "through", "during", "before", "after", "and",
            "but", "or", "nor", "not", "no", "if", "then", "than", "that",
            "this", "it", "its", "they", "them", "their", "we", "our",
            "you", "your", "he", "she", "his", "her",
        }

    def _flatten_to_tokens(self, obj: dict | list | str, depth: int = 0) -> set[str]:
        if depth > 5:
            return set()
        tokens: set[str] = set()
        if isinstance(obj, dict):
            for k, v in obj.items():
                tokens.update(k.lower().replace("_", " ").split())
                tokens.update(self._flatten_to_tokens(v, depth + 1))
        elif isinstance(obj, list):
            for item in obj:
                tokens.update(self._flatten_to_tokens(item, depth + 1))
        elif isinstance(obj, str):
            tokens.update(obj.lower().replace("_", " ").split())
        return tokens

    # ================================================================
    # Doctrinal coherence rules
    # ================================================================

    _FIRES_ACTIONS = {
        "establish_final_protective_fires", "register_target_reference_points",
        "establish_fire_support_triggers", "call_for_fire", "fire_support",
        "indirect_fire", "close_air_support",
    }

    _MANEUVER_ACTIONS = {
        "establish_engagement_area", "position_direct_fire_weapons",
        "coordinate_obstacle_plan", "establish_advance_guard",
        "establish_movement_formation", "designate_phase_lines",
        "establish_strongpoints", "prepare_engagement_areas_between_buildings",
        "establish_observation_posts", "assault", "attack", "movement_to_contact",
    }

    _SECURITY_ACTIONS = {
        "establish_advance_guard", "establish_observation_posts",
        "establish_screen", "establish_guard", "establish_cover",
        "route_reconnaissance", "area_reconnaissance",
    }

    _SEQUENCING_RULES: list[tuple[str, str, str]] = [
        (
            "fire_support",
            "maneuver",
            "Doctrine requires fires to be coordinated before maneuver elements commit",
        ),
        (
            "reconnaissance",
            "movement",
            "Doctrine requires reconnaissance before committing the main body to movement",
        ),
    ]

    def _check_doctrinal_coherence(
        self,
        artifact: DecisionArtifact,
        codex_objects: list[CodexObject],
        action_validation: dict,
        chain_results: list[CausalChainResult],
    ) -> list[CoherenceCheckResult]:
        results: list[CoherenceCheckResult] = []

        guidance_actions = set()
        for obj in codex_objects[:2]:
            for a in obj.allowed_actions:
                guidance_actions.add(a.action.lower())

        proposed_actions = {a.action.lower() for a in artifact.proposed_actions}
        all_actions = guidance_actions | proposed_actions

        phase = ""
        mission_type = ""
        if codex_objects and codex_objects[0].context_envelope:
            phase = (codex_objects[0].context_envelope.phase or "").lower()
            mission_type = (codex_objects[0].context_envelope.mission_type or "").lower()

        results.append(self._coherence_fires_maneuver(all_actions, phase))
        results.append(self._coherence_reserve_maintenance(
            all_actions, codex_objects, phase,
        ))
        results.append(self._coherence_security_element(
            all_actions, phase, mission_type,
        ))
        results.append(self._coherence_constraint_awareness(
            artifact, codex_objects,
        ))
        results.append(self._coherence_effects_alignment(
            artifact, codex_objects,
        ))

        return results

    def _coherence_fires_maneuver(
        self, all_actions: set[str], phase: str,
    ) -> CoherenceCheckResult:
        """Warfighting function integration: fires and maneuver should both
        be represented in offensive or defensive operations."""
        has_fires = bool(all_actions & self._FIRES_ACTIONS)
        has_maneuver = bool(all_actions & self._MANEUVER_ACTIONS)
        is_combat_phase = any(
            kw in phase for kw in ("offensive", "defensive", "attack", "defense")
        )

        if not is_combat_phase:
            return CoherenceCheckResult(
                rule_id="COH-001",
                rule_name="fires_maneuver_integration",
                passed=True,
                detail="Non-combat phase -- fires/maneuver integration check not applicable",
                category="warfighting_function",
            )

        if has_fires and has_maneuver:
            return CoherenceCheckResult(
                rule_id="COH-001",
                rule_name="fires_maneuver_integration",
                passed=True,
                detail="Both fires and maneuver actions present -- warfighting functions synchronized",
                category="warfighting_function",
            )

        missing = []
        if not has_fires:
            missing.append("fires")
        if not has_maneuver:
            missing.append("maneuver")
        return CoherenceCheckResult(
            rule_id="COH-001",
            rule_name="fires_maneuver_integration",
            passed=False,
            detail=(
                f"Combat operations without {' or '.join(missing)} actions. "
                "Doctrine requires synchronization across warfighting functions."
            ),
            category="warfighting_function",
        )

    def _coherence_reserve_maintenance(
        self,
        all_actions: set[str],
        codex_objects: list[CodexObject],
        phase: str,
    ) -> CoherenceCheckResult:
        """Principle check: defensive operations should maintain a reserve."""
        is_defensive = "defensive" in phase or "defense" in phase

        if not is_defensive:
            return CoherenceCheckResult(
                rule_id="COH-002",
                rule_name="reserve_maintenance",
                passed=True,
                detail="Non-defensive phase -- reserve check not applicable",
                category="principle",
            )

        reserve_mentioned = False
        for obj in codex_objects:
            if any("reserve" in c.lower() for c in obj.constraints):
                reserve_mentioned = True
                break
            for t in obj.tradeoffs:
                if "reserve" in t.action.lower() or "reserve" in t.degradation.lower():
                    reserve_mentioned = True
                    break

        if reserve_mentioned:
            return CoherenceCheckResult(
                rule_id="COH-002",
                rule_name="reserve_maintenance",
                passed=True,
                detail="Defensive plan addresses reserve -- aligns with principle of retaining flexibility",
                category="principle",
            )

        return CoherenceCheckResult(
            rule_id="COH-002",
            rule_name="reserve_maintenance",
            passed=False,
            detail=(
                "Defensive operations with no mention of reserve element. "
                "Doctrine emphasizes retaining a reserve to exploit success "
                "or respond to enemy penetration."
            ),
            category="principle",
        )

    def _coherence_security_element(
        self,
        all_actions: set[str],
        phase: str,
        mission_type: str,
    ) -> CoherenceCheckResult:
        """Principle check: offensive movement should include a security element."""
        is_offensive_movement = (
            "offensive" in phase
            or "movement_to_contact" in mission_type
            or "attack" in mission_type
        )

        if not is_offensive_movement:
            return CoherenceCheckResult(
                rule_id="COH-003",
                rule_name="security_element",
                passed=True,
                detail="Non-offensive-movement phase -- security element check not applicable",
                category="principle",
            )

        has_security = bool(all_actions & self._SECURITY_ACTIONS)
        if has_security:
            return CoherenceCheckResult(
                rule_id="COH-003",
                rule_name="security_element",
                passed=True,
                detail="Security/reconnaissance element present -- aligns with principle of security",
                category="principle",
            )

        return CoherenceCheckResult(
            rule_id="COH-003",
            rule_name="security_element",
            passed=False,
            detail=(
                "Offensive movement without a security or reconnaissance element. "
                "Doctrine requires the force to never move without security to prevent surprise."
            ),
            category="principle",
        )

    def _coherence_constraint_awareness(
        self,
        artifact: DecisionArtifact,
        codex_objects: list[CodexObject],
    ) -> CoherenceCheckResult:
        """Check that the artifact acknowledges constraints imposed by doctrine,
        especially high-stakes ones like civilian protection or ROE."""
        doctrinal_constraints = set()
        for obj in codex_objects:
            for c in obj.constraints:
                doctrinal_constraints.add(c.lower())

        high_stakes = {
            c for c in doctrinal_constraints
            if any(kw in c for kw in ("civilian", "roe", "collateral", "protected", "safe_distance"))
        }

        if not high_stakes:
            return CoherenceCheckResult(
                rule_id="COH-004",
                rule_name="constraint_awareness",
                passed=True,
                detail="No high-stakes constraints in matched doctrine",
                category="principle",
            )

        artifact_constraint_text = " ".join(
            c.value.lower() for c in artifact.constraints
        )
        acknowledged = set()
        for hs in high_stakes:
            key_terms = set(hs.replace("_", " ").split()) - self._stop_words()
            if any(term in artifact_constraint_text for term in key_terms):
                acknowledged.add(hs)

        if not artifact.constraints:
            return CoherenceCheckResult(
                rule_id="COH-004",
                rule_name="constraint_awareness",
                passed=False,
                detail=(
                    f"Doctrine imposes high-stakes constraints "
                    f"({', '.join(high_stakes)}) but the artifact includes no "
                    f"constraints. Operational plan should acknowledge doctrinal constraints."
                ),
                category="principle",
            )

        return CoherenceCheckResult(
            rule_id="COH-004",
            rule_name="constraint_awareness",
            passed=True,
            detail=f"Artifact includes constraints; doctrinal constraints acknowledged",
            category="principle",
        )

    def _coherence_effects_alignment(
        self,
        artifact: DecisionArtifact,
        codex_objects: list[CodexObject],
    ) -> CoherenceCheckResult:
        """Check that proposed actions' intended effects align with the
        doctrinal intended effects -- are we trying to achieve what doctrine
        says this type of operation should achieve?

        Compares against both object-level intended effects and the
        action-level intended effects on CODEX allowed actions, since
        these operate at different abstraction levels."""
        if not artifact.proposed_actions:
            return CoherenceCheckResult(
                rule_id="COH-005",
                rule_name="effects_alignment",
                passed=True,
                detail="No proposed actions to check effects alignment",
                category="warfighting_function",
            )

        doctrinal_effects: set[str] = set()
        for obj in codex_objects:
            for eff in obj.intended_effects:
                doctrinal_effects.update(
                    set(eff.lower().replace("_", " ").split()) - self._stop_words()
                )
            for action in obj.allowed_actions:
                for eff in action.intended_effects:
                    doctrinal_effects.update(
                        set(eff.lower().replace("_", " ").split()) - self._stop_words()
                    )

        proposed_effects: set[str] = set()
        for pa in artifact.proposed_actions:
            for ie in pa.intended_effects:
                proposed_effects.update(
                    set(ie.lower().replace("_", " ").split()) - self._stop_words()
                )

        if not proposed_effects:
            return CoherenceCheckResult(
                rule_id="COH-005",
                rule_name="effects_alignment",
                passed=True,
                detail="Proposed actions do not specify intended effects -- cannot assess alignment",
                category="warfighting_function",
            )

        if not doctrinal_effects:
            return CoherenceCheckResult(
                rule_id="COH-005",
                rule_name="effects_alignment",
                passed=True,
                detail="CODEX objects do not specify intended effects",
                category="warfighting_function",
            )

        overlap = proposed_effects & doctrinal_effects
        alignment_ratio = len(overlap) / len(proposed_effects)
        if alignment_ratio >= 0.25:
            return CoherenceCheckResult(
                rule_id="COH-005",
                rule_name="effects_alignment",
                passed=True,
                detail=(
                    f"Proposed effects align with doctrinal intended effects "
                    f"({alignment_ratio:.0%} token overlap)"
                ),
                category="warfighting_function",
            )

        return CoherenceCheckResult(
            rule_id="COH-005",
            rule_name="effects_alignment",
            passed=False,
            detail=(
                f"Proposed effects diverge from doctrinal intended effects "
                f"({alignment_ratio:.0%} alignment). The plan may be trying to achieve "
                f"outcomes not aligned with what doctrine expects for this mission type."
            ),
            category="warfighting_function",
        )

    # ================================================================
    # Coverage and guidance
    # ================================================================

    def _assess_coverage(
        self, artifact: DecisionArtifact, codex_objects: list[CodexObject]
    ) -> dict:
        if not codex_objects:
            return {"type": None}

        best = codex_objects[0]
        if not artifact.context_envelope or not best.context_envelope:
            gaps = self._identify_coverage_gaps(artifact, codex_objects)
            return {
                "type": "analogous",
                "basis": best.provenance,
                "gaps": gaps,
                "analogy_basis": f"Matched on keyword/trigger overlap without context envelope alignment",
            }

        ce = artifact.context_envelope
        bc = best.context_envelope

        field_matches = 0
        field_total = 0
        gaps = []

        if ce.mission_type and bc.mission_type:
            field_total += 1
            if ce.mission_type.lower() == bc.mission_type.lower():
                field_matches += 1
            else:
                gaps.append(f"mission_type: requested '{ce.mission_type}', matched '{bc.mission_type}'")

        if ce.echelon and bc.echelon:
            field_total += 1
            if ce.echelon.lower() == bc.echelon.lower():
                field_matches += 1
            else:
                gaps.append(f"echelon: requested '{ce.echelon}', matched '{bc.echelon}'")

        if ce.phase and bc.phase:
            field_total += 1
            if ce.phase.lower() == bc.phase.lower():
                field_matches += 1
            else:
                gaps.append(f"phase: requested '{ce.phase}', matched '{bc.phase}'")

        if ce.domain and bc.domain:
            field_total += 1
            if ce.domain.lower() == bc.domain.lower():
                field_matches += 1
            else:
                gaps.append(f"domain: requested '{ce.domain}', matched '{bc.domain}'")

        structural_gaps = self._identify_coverage_gaps(artifact, codex_objects)
        gaps.extend(structural_gaps)

        if field_total > 0 and field_matches == field_total and not structural_gaps:
            return {"type": "direct", "basis": best.provenance}

        if field_total > 0 and field_matches == field_total:
            return {"type": "direct", "basis": best.provenance, "gaps": structural_gaps}

        if field_total > 0 and field_matches > 0:
            return {
                "type": "partial" if gaps else "analogous",
                "basis": best.provenance,
                "gaps": gaps,
            }

        return {
            "type": "analogous",
            "basis": best.provenance,
            "gaps": gaps,
            "analogy_basis": f"Best match: {best.codex_id} ({bc.mission_type or 'unknown'} at {bc.echelon or 'unknown'} echelon)",
        }

    def _identify_coverage_gaps(
        self, artifact: DecisionArtifact, codex_objects: list[CodexObject]
    ) -> list[str]:
        """Identify structural gaps between what the artifact needs and what CODEX covers."""
        gaps = []
        if artifact.proposed_actions:
            allowed = set()
            for obj in codex_objects:
                for a in obj.allowed_actions:
                    allowed.add(a.action.lower())
            for pa in artifact.proposed_actions:
                if pa.action.lower() not in allowed:
                    gaps.append(f"proposed_action '{pa.action}' has no CODEX coverage")
        return gaps

    def _build_guidance(
        self, artifact: DecisionArtifact, codex_objects: list[CodexObject], action_validation: dict
    ) -> list[dict]:
        actions = []
        seq = 1
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

    # ================================================================
    # Meta-evaluation (trust / caution)
    # ================================================================

    def _build_meta(
        self,
        artifact: DecisionArtifact,
        codex_objects: list[CodexObject],
        coverage: dict,
        completeness: float,
        confidence: float,
        precondition_issues: list[str],
        missing_observations: list[str],
        constraint_conflicts: list[str],
        tradeoffs: list[dict],
        chain_results: list[CausalChainResult],
        action_validation: dict,
        coherence_results: list[CoherenceCheckResult],
        trace: list[str],
    ) -> MetaEvaluationDetail:
        trust: list[str] = []
        caution: list[str] = []

        # --- Trust factors ---
        if coverage["type"] == "direct":
            trust.append("Direct doctrinal match -- guidance maps to compiled, SME-validated CODEX objects")
        if not precondition_issues:
            trust.append("All stated preconditions verified")
        if not missing_observations:
            trust.append("All required observations confirmed")
        satisfied_chains = [cr for cr in chain_results if cr.satisfied]
        if satisfied_chains:
            names = [cr.pattern_name for cr in satisfied_chains]
            trust.append(f"Causal reasoning chains fully satisfied: {', '.join(names)}")
        if action_validation["aligned"]:
            trust.append(
                f"Proposed actions align with CODEX allowed actions: "
                f"{', '.join(action_validation['aligned'])}"
            )
        if completeness >= 0.85:
            trust.append("Artifact is highly complete -- evaluation based on rich contextual information")
        if len(codex_objects) >= 2:
            trust.append(f"Multiple CODEX objects reinforce guidance ({len(codex_objects)} matched)")

        # --- Caution factors ---
        if coverage["type"] == "analogous":
            caution.append(
                "Coverage is analogous, not direct -- guidance derived from similar but not "
                "identical doctrinal context. SME review recommended before execution."
            )
        if precondition_issues:
            caution.append(f"Unverified preconditions: {', '.join(precondition_issues)}")
        if missing_observations:
            caution.append(
                f"Required observations not confirmed: {', '.join(missing_observations)}. "
                "Guidance assumes these will be satisfied."
            )
        if constraint_conflicts:
            caution.append(f"Potential constraint conflicts detected: {', '.join(constraint_conflicts)}")
        if tradeoffs:
            names = [t["tradeoff"] for t in tradeoffs]
            caution.append(
                f"Active tradeoffs in play: {', '.join(names)}. "
                "Each involves a capability degradation -- review compensations."
            )
        broken_chains = [cr for cr in chain_results if not cr.satisfied]
        if broken_chains:
            for cr in broken_chains:
                reason = cr.broken_reason or "unknown"
                caution.append(
                    f"Causal chain '{cr.pattern_name}' broken at '{cr.broken_at}': {reason}. "
                    "Doctrinal reasoning pattern may not hold in current situation."
                )
        if action_validation["unrecognized"]:
            caution.append(
                f"Proposed actions not found in CODEX allowed actions: "
                f"{', '.join(action_validation['unrecognized'])}. "
                "These are outside compiled doctrinal guidance."
            )
        if completeness < 0.6:
            caution.append(
                f"Artifact completeness is low ({completeness:.0%}). "
                "Evaluation based on limited information."
            )

        # --- Doctrinal coherence factors ---
        passed_coherence = [c for c in coherence_results if c.passed]
        failed_coherence = [c for c in coherence_results if not c.passed]
        for cc in passed_coherence:
            if "not applicable" not in cc.detail.lower():
                trust.append(f"Coherence: {cc.detail}")
        for cc in failed_coherence:
            caution.append(f"Coherence: {cc.detail}")

        # --- Grounding label ---
        grounding = coverage["type"] or "none"

        # --- Novel situation ---
        novel = coverage["type"] in ("analogous", "partial", None)

        # --- Recommendation ---
        if not caution:
            recommendation = "High confidence. Guidance is directly grounded in compiled doctrine with no outstanding conditions."
        elif len(trust) >= len(caution):
            recommendation = (
                "Moderate confidence. Guidance is doctrinally grounded but has conditions that "
                "should be resolved. Review caution factors before execution."
            )
        else:
            recommendation = (
                "Low confidence. Multiple caution factors present. Human review strongly "
                "recommended before acting on this guidance."
            )

        return MetaEvaluationDetail(
            trust_factors=trust,
            caution_factors=caution,
            doctrinal_grounding=grounding,
            novel_situation=novel,
            response_completeness=completeness,
            recommendation=recommendation,
            coherence_checks=coherence_results,
        )

    def _build_meta_no_coverage(
        self, artifact: DecisionArtifact, trace: list[str]
    ) -> MetaEvaluationDetail:
        return MetaEvaluationDetail(
            trust_factors=[],
            caution_factors=[
                "No CODEX objects match this request. The system has no compiled "
                "doctrinal basis for providing guidance.",
                "This may indicate the request falls outside the current doctrinal "
                "corpus, or the request lacks sufficient context for matching.",
            ],
            doctrinal_grounding="none",
            novel_situation=True,
            response_completeness=self._assess_completeness(artifact, {}),
            recommendation=(
                "No doctrinal coverage available. This request cannot be evaluated "
                "against compiled doctrine. Human judgment required."
            ),
        )

    def _build_meta_sparse(
        self,
        artifact: DecisionArtifact,
        completeness: float,
        codex_objects: list[CodexObject],
        trace: list[str],
    ) -> MetaEvaluationDetail:
        trust: list[str] = []
        if codex_objects:
            trust.append(
                f"Potentially relevant CODEX objects identified: "
                f"{', '.join(obj.codex_id for obj in codex_objects[:3])}"
            )

        return MetaEvaluationDetail(
            trust_factors=trust,
            caution_factors=[
                f"Artifact completeness is {completeness:.0%} -- too sparse for confident evaluation.",
                "System is requesting clarification to improve evaluation quality.",
            ],
            doctrinal_grounding="none",
            novel_situation=False,
            response_completeness=completeness,
            recommendation=(
                "Insufficient information for evaluation. Respond to clarification "
                "questions to enable doctrinal assessment."
            ),
        )

    # ================================================================
    # Novel situation degradation
    # ================================================================

    def _find_nearest_partial(
        self, artifact: DecisionArtifact, codex_objects: list[CodexObject]
    ) -> str | None:
        """When no CODEX objects match, describe what partial matches exist
        so the consumer understands why coverage failed."""
        return None

    # ================================================================
    # Clarification question generation
    # ================================================================

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
        questions: list[dict] = []
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
                        "reason_needed": "Required observation for doctrinal evaluation",
                        "expected_format": "boolean_with_detail",
                    })
                    q_id += 1

        return questions[:5]
