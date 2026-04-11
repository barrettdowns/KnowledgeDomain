# CODEX/WARBRAIN Conversation Layer -- Technical Roadmap

## Current Limitations, Future Enhancements, and Production Validation

---

## 1. Doctrinal Coherence Validation

> **Implementation Status: PARTIALLY IMPLEMENTED.** Five initial coherence rules are built and operational in the rule engine (COH-001 through COH-005): fires-maneuver integration, reserve maintenance, security element presence, high-stakes constraint awareness, and effects alignment. Sequencing norm constants are defined in the engine but not yet wired into evaluation. Additional rules for force ratio reasonableness, doctrinal anti-patterns, and broader sequencing validation require SME authorship.

### The Gap

The current meta-evaluation answers the question "does this response structurally match compiled doctrine?" It checks fields, validates preconditions, walks causal chains. What it does not answer is: "does this response make sense the way the Army thinks?"

Those are different questions. The structural checks can confirm that an engagement area is a doctrinally valid action for area defense and that the preconditions are met. But they can't catch things like:

- A battalion-level COA that commits the reserve in the opening phase with no subsequent plan to reconstitute it -- structurally valid (reserve commitment is an allowed action) but doctrinally suspect (you don't give up your flexibility before you understand the situation).
- A defensive plan that positions all fires on a single avenue of approach with no coverage of alternate routes -- every individual action is doctrinally sound, but the combination violates the principle of mutual support.
- An offensive COA that proposes maneuver without establishing fire superiority first -- each action is allowed, but the sequence contradicts fundamental doctrine.
- A force ratio of 1:1 for a deliberate attack in urban terrain -- nothing in the CODEX object flags the ratio because force ratios are situational, but any Army planner would flag this as insufficient.

These are not structural alignment failures. They are doctrinal coherence failures -- the response doesn't align with how the Army reasons at a higher level than individual actions and constraints.

### Recommended Approach: Doctrinal Coherence Rules

Encode cross-cutting Army doctrinal principles as a separate rule set that evaluates the overall coherence of an artifact and its proposed guidance, not just the field-by-field alignment with CODEX objects. These would function as a second validation layer within the meta-evaluation.

**Categories of coherence rules:**

**Warfighting function integration.** Doctrine requires synchronization across warfighting functions. A COA that addresses maneuver without fires, or fires without maneuver, is incomplete. Coherence rules would check: does the guidance span the expected warfighting functions for this mission type? If the CODEX objects include fire support actions but the artifact's proposed actions are all maneuver, flag it.

**Doctrinal principles.** The Army's operational framework includes principles that apply across mission types: mass, economy of force, security, surprise, unity of command, etc. These could be encoded as pattern checks. "Mass" means concentrating effects at the decisive point -- a coherence rule could check whether the guidance concentrates actions on identified key terrain or spreads them uniformly. "Security" means never leaving the force unprotected -- a coherence rule could check whether the guidance maintains a reserve or rear security element.

**Sequencing norms.** Certain action sequences are deeply ingrained in Army planning. Reconnaissance before maneuver. Fire superiority before assault. Consolidation after objective seizure. These could be encoded as ordered-pair rules: "if action A is in the guidance, action B should precede it."

**Force ratio reasonableness.** If the artifact includes force composition data for both friendly and enemy, coherence rules could flag ratios that doctrine considers insufficient for the proposed mission type (e.g., less than 3:1 for deliberate attack, less than 6:1 for urban operations).

**Anti-patterns.** Things doctrine explicitly warns against: piecemeal commitment, attacking on multiple axes without sufficient combat power on each, defensive plans with no depth, etc. These could be encoded as negative pattern checks that produce caution factors when detected.

### Implementation Path

These coherence rules would be:
- **Authored by SMEs**, not extracted by LLM. They represent institutional knowledge about how the Army thinks at the operational level, not what's written in a specific paragraph.
- **Stored as a separate rule library**, not inside CODEX objects. They are cross-cutting principles that apply regardless of which CODEX objects are retrieved.
- **Evaluated after structural checks and causal chains**, as a final "sanity check" layer.
- **Surfaced as trust or caution factors** in the existing meta-evaluation. "Coherence check: guidance maintains reserve element -- aligns with principle of security" (trust). "Coherence check: proposed maneuver without fire superiority -- diverges from standard offensive sequencing" (caution).
- **Deterministic**, like everything else in the rule engine. Each coherence rule is a structural check with a defined trigger condition and output.

### Complexity Level: Moderate

This is feasible without an LLM. The coherence rules are essentially pattern matchers over the combined set of proposed actions, CODEX guidance, and situational context. The hard part is authoring the rules correctly -- that requires SME involvement. The implementation is straightforward conditional logic.

---

## 2. Current Limitations and Future Enhancement Recommendations

### 2.1 Causal Chain Evaluation Uses Token-Based Matching

> **Implementation Status: IMPLEMENTED (token-based).** The token-based matching described below is fully built and operational. Enhancement to phrase-level embeddings or structured predicates is future work.

**Current state:** The rule engine evaluates causal chain conditions by tokenizing the condition phrase and checking for overlap against tokenized artifact evidence. This uses stop-word filtering and a 40% meaningful-token threshold. It works for the current CODEX objects but can produce false positives or misses when condition phrases are ambiguous or share vocabulary with unrelated context.

**Impact:** A condition like "enemy_movement_disrupted" might match against unrelated tokens if the artifact happens to contain both "enemy" and "movement" in different contexts. The stop-word filter and threshold mitigate this but don't eliminate it.

**Recommended enhancement:** Replace token-based matching with phrase-level matching using pre-computed phrase embeddings. At CODEX object compilation time, compute embeddings for each causal link condition and exception. At evaluation time, embed the artifact's evidence fields and compute cosine similarity. This preserves determinism (same embeddings always produce the same similarity scores) while dramatically improving matching accuracy. No LLM call at query time -- the embeddings are pre-computed and stored alongside the CODEX objects.

**Alternatively,** the causal link conditions could be rewritten as structured predicates during ingestion -- `{"field": "observations", "contains": "enemy_movement_disrupted"}` -- making the evaluation a direct lookup rather than a fuzzy match. This is simpler and fully deterministic but requires more precision during CODEX compilation.

### 2.2 Limited Compositional Reasoning Across CODEX Objects

> **Implementation Status: NOT YET IMPLEMENTED.** The engine evaluates the top 2 objects but does not follow cross-references to pull in additional objects.

**Current state:** The rule engine evaluates the top 2 most relevant CODEX objects. Causal chains carry cross-references to other CODEX objects, but the engine doesn't follow those references to pull in additional objects or evaluate inter-object interactions.

**Impact:** Complex scenarios involving 4-6 doctrinal domains (maneuver + fires + logistics + air defense + information + engineering) may not get full coverage from only 2 objects.

**Recommended enhancement:** Implement a cross-reference expansion step. After initial retrieval, scan the causal chain cross-references on the returned CODEX objects and pull in any referenced objects that weren't already retrieved. Evaluate all of them, but weight guidance from the primary objects higher than cross-referenced objects. This stays deterministic and doesn't require an LLM.

### 2.3 No Graduated Analogy Scoring

> **Implementation Status: NOT YET IMPLEMENTED.** Coverage classification (direct/analogous/partial) is operational, but no weighted similarity scoring exists.

**Current state:** Coverage is classified as direct, analogous, or partial based on context envelope field matching. There is no measure of how close an analogy is.

**Impact:** "Area defense at battalion" matched against "area defense at brigade" gets the same "analogous" label as "area defense" matched against "movement to contact." The first is a much closer analogy than the second, but the system doesn't distinguish them.

**Recommended enhancement:** Define a weighted similarity function over context envelope fields. Mission type match could carry the most weight (same mission type at different echelon is a close analogy), followed by phase, echelon, and domain. The similarity score would produce a finer-grained coverage signal: "analogous (high similarity)" vs. "analogous (low similarity)." This is straightforward arithmetic on enumerated field values and requires no LLM.

### 2.4 No Temporal Sequencing Validation

> **Implementation Status: NOT YET IMPLEMENTED.** Sequencing rule constants (fires before maneuver, reconnaissance before movement) are defined in the rule engine but not wired into the evaluation pipeline.

**Current state:** Guidance actions are returned in sequence, but the rule engine does not validate whether the proposed sequence follows doctrinal norms.

**Impact:** A machine could propose assaulting an objective before establishing fire superiority, and the system would evaluate each action independently without flagging the sequencing issue.

**Recommended enhancement:** Add an optional `sequencing_constraints` field to CODEX objects: ordered pairs of actions where one must precede the other. The rule engine validates proposed action sequences against these constraints and flags violations as caution factors. This is a straightforward ordering check.

### 2.5 Truly Novel Situations

> **Implementation Status: PARTIALLY IMPLEMENTED.** Clean abstention with explanation is fully operational. A `_find_nearest_partial` stub exists for nearest-neighbor fallback but returns `None` -- the matching logic is not yet built. LLM fallback layer is not implemented.

**Current state:** When no CODEX objects match, the system abstains cleanly with an explanation. It cannot generate guidance from first principles or reason by analogy beyond the compiled objects.

**Impact:** The system is silent on situations that fall outside the compiled corpus, even when a human SME could extrapolate from adjacent doctrine.

**Recommended enhancement (short-term):** Implement a "nearest neighbor" fallback. When no objects meet the relevance threshold, lower the threshold and return the closest partial matches with explicit `extrapolated` coverage labeling and heavy caution factors. The machine gets something rather than nothing, clearly marked as extrapolated.

**Recommended enhancement (long-term):** Add an optional LLM reasoning layer that activates only when the rule engine abstains. The LLM receives the artifact and the nearest CODEX objects (even if below threshold) and generates a best-effort evaluation. This response would carry distinct labeling (`doctrinal_grounding: "llm_extrapolated"`) and would always include a caution factor that it was generated by LLM reasoning, not deterministic evaluation. The LLM is never in the primary path -- it's a fallback for edge cases.

### 2.6 Natural Language / Unstructured Input

> **Implementation Status: NOT YET IMPLEMENTED.**

**Current state:** The system requires fully structured JSON artifacts. It cannot process free-text situation descriptions, narrative objectives, or unstructured fields.

**Impact:** If a consuming machine cannot produce structured artifacts (e.g., voice-to-text systems, chat-based interfaces), it cannot use the API directly.

**Recommended enhancement:** Add an optional NLP preprocessing layer that converts unstructured text into a structured `DecisionArtifact` before it enters the rule engine. This layer would use an LLM to extract artifact type, objective, situation fields, proposed actions, etc. from natural language. It sits in front of the conversation layer, not inside it -- the rule engine still receives and evaluates structured data. The preprocessing layer would add a caution factor noting that the artifact was derived from unstructured input.

### 2.7 Rule Engine Is Only as Good as the Compiled CODEX Objects

> **Implementation Status: NOT YET IMPLEMENTED.** No quality scoring system exists for CODEX objects.

**Current state:** If a doctrinal concept was not extracted during ingestion -- a causal chain was missed, a constraint wasn't compiled, a tradeoff wasn't captured -- the rule engine has no way to surface it.

**Impact:** Gaps in CODEX object quality directly translate to gaps in evaluation quality.

**Recommended enhancement:** Implement a CODEX object quality scoring system. At ingestion time, measure coverage metrics: does this object have triggers? Required observations? At least one causal chain? Constraints? Tradeoffs? Provenance? Objects below a quality threshold get flagged for SME enrichment. The conversation layer could also surface a caution factor when guidance is derived from CODEX objects with low quality scores.

### 2.8 Template-Based Question Generation

> **Implementation Status: IMPLEMENTED (generic templates).** The rule engine generates clarification questions based on missing artifact fields and unconfirmed CODEX required observations. Enhancement to context-aware, CODEX-object-specific question templates is future work.

**Current state:** Clarification questions are generated from templates based on which artifact fields are missing. The questions are generic: "What is the composition and strength of friendly forces?" regardless of the specific operational context.

**Impact:** The questions are functionally correct but not contextually tailored. A movement-to-contact scenario and an area defense scenario get the same friendly-forces question.

**Recommended enhancement:** Add context-aware question templates to CODEX objects. Each object could carry a `clarification_templates` field with questions specific to its doctrinal context. When the rule engine abstains and needs to ask questions, it draws from the matched CODEX object's templates first, then falls back to generic templates. This keeps question generation deterministic while making it contextually relevant.

### 2.9 No Learning or Adaptation from Evaluation Outcomes

> **Implementation Status: NOT YET IMPLEMENTED.** The audit trail captures all data needed for analytics, but no pipeline processes it.

**Current state:** The rule engine does not learn from past evaluations. The same CODEX objects and rules are applied regardless of historical patterns.

**Impact:** If a particular type of request consistently triggers the same caution factors, or if human reviewers consistently override a particular evaluation, the system has no mechanism to adapt.

**Recommended enhancement:** Implement an analytics pipeline over the audit trail. Aggregate patterns: which caution factors appear most frequently? Which evaluations get overridden by human reviewers? Which CODEX objects are retrieved but rarely produce supported outcomes? This analytics output feeds back to the ingestion team and SMEs as CODEX object improvement signals -- not as runtime rule changes, but as a quality improvement loop. The rule engine itself stays deterministic; the CODEX objects it evaluates against get better over time.

---

## 3. Production Validation Recommendations

> **Implementation Status: ALL PLANNED, NOT YET IMPLEMENTED.** The recommendations below describe the validation strategy for production deployment. None are built yet. The deterministic rule engine's reproducibility makes all of these feasible with exact-match assertions.

### 3.1 Ground-Truth Test Suites

Build a corpus of known-good evaluations: specific artifacts paired with specific CODEX objects and the expected evaluation outcome, trust factors, and caution factors. Run the full suite on every rule engine change. Because the engine is deterministic, tests can assert exact equality -- not statistical similarity, exact match. This is the primary regression safety net.

**Implementation:** A JSON file of test cases, each containing an inbound artifact, a set of CODEX objects, and the expected `RuleEngineResult` fields. A test runner loads each case, runs the evaluation, and asserts equality on evaluation outcome, trust factors, caution factors, coverage type, and guidance actions. Integrate with CI/CD so every code change runs the suite automatically.

### 3.2 SME-Authored Evaluation Scenarios

Subject matter experts create scenario packs: a realistic decision artifact, the operational context it represents, the expected evaluation outcome, and annotations explaining why. These serve two purposes: they validate the rule engine's logic, and they validate the CODEX objects' completeness. If an SME expects "supported" but the system returns "conditional" because a causal chain broke, that either reveals a rule engine bug or a CODEX object gap.

**Implementation:** A structured scenario format with fields for the artifact, expected outcome, expected key trust/caution factors, and SME rationale. Scenarios are version-controlled alongside the CODEX objects. New scenarios are added whenever a new mission type or operational context is supported.

### 3.3 Sensitivity Analysis

Systematically vary individual fields on known-good artifacts and measure evaluation changes. This maps the decision boundaries: which field changes flip an evaluation from supported to conditional? Which observations are load-bearing? Which causal chains are fragile? This identifies both overly sensitive rules (a minor field change causes a dramatic outcome shift) and insufficiently sensitive rules (removing a critical observation doesn't change the outcome).

**Implementation:** An automated harness that takes a baseline artifact, generates variants (remove one observation, change one precondition, alter one context envelope field), runs each variant through the engine, and produces a diff report showing which changes affected the outcome and how.

### 3.4 Causal Chain Validation

Validate causal chains independently from the rule engine. For each chain in each CODEX object, an SME reviews: does the IF/THEN/BECAUSE/UNLESS accurately represent the doctrinal logic? Are the exception conditions correct and complete? Is the provenance citation accurate? Are there missing links?

**Implementation:** A review workflow where each causal chain is presented to an SME with its source doctrine excerpt. The SME marks it as validated, needs revision, or rejected. Validation status is stored on the CODEX object. The rule engine could surface a caution factor when using unvalidated chains.

### 3.5 Shadow Mode

In a production deployment, run the rule engine in parallel with whatever system or process currently provides guidance. Compare outputs. Where they diverge, human reviewers adjudicate which was correct. Over time, this builds an empirical validation corpus and identifies systematic biases in the rule engine.

**Implementation:** A logging adapter that captures both the rule engine's evaluation and the reference system's output for the same inbound artifact, stores them side by side, and flags divergences for review.

### 3.6 Rule Engine Trace Auditing

Every evaluation produces a full decision trace. A periodic audit process samples traces and has SMEs review them for correctness. Not just "was the outcome right?" but "did the engine reach the right conclusion for the right reasons?" Did it correctly identify the broken causal chain? Did it miss a relevant check? Did the meta-evaluation accurately reflect the situation?

**Implementation:** A sampling framework that selects traces based on criteria: random sampling for baseline, plus targeted sampling of edge cases (evaluations near decision boundaries, evaluations with many caution factors, evaluations that produced abstain). SME reviewers score each trace on a rubric.

### 3.7 Coverage Analysis

Measure what percentage of inbound artifacts get each evaluation outcome. A high abstain rate may indicate CODEX objects are too narrow or the retriever is missing matches. A low abstain rate on known-out-of-scope requests may indicate rules are too permissive. Track coverage metrics over time as CODEX objects are added and refined.

**Implementation:** A dashboard over the audit trail that shows evaluation outcome distribution, abstain reasons, coverage types, most-retrieved CODEX objects, most-common caution factors, and completeness distributions. This is operational intelligence about the system's behavior, not a validation test per se, but it reveals systematic issues that tests might miss.

### 3.8 Adversarial Testing

Deliberately craft artifacts designed to test edge cases and failure modes:
- Artifacts that should trigger specific caution factors -- verify they do.
- Artifacts with internally contradictory fields (e.g., defensive mission type with offensive triggers) -- verify the system flags the incoherence.
- Artifacts with preconditions marked as verified that shouldn't be -- verify the system doesn't perform its own judgment on precondition validity (it should trust what the artifact claims, since it has no independent observation capability).
- Artifacts that closely resemble valid scenarios but have subtle doctrinal errors -- measure whether the system catches them or passes them through.

**Implementation:** An adversarial test suite maintained by both engineers and SMEs. Engineers focus on structural edge cases (empty fields, maximum-length inputs, unusual type combinations). SMEs focus on doctrinal edge cases (plausible but flawed COAs, correct actions in wrong sequence, appropriate actions in wrong context).

---

## Summary: Enhancement Priority

| Enhancement | Complexity | Impact | Requires LLM | Priority | MVP Status |
|---|---|---|---|---|---|
| Doctrinal coherence rules | Moderate | High | No | Near-term | **Partial** -- 5 rules built, more need SME authorship |
| Causal chain phrase matching | Low-Moderate | Medium | No (pre-computed embeddings) | Near-term | **Implemented** (token-based; phrase embeddings are the enhancement) |
| Cross-reference expansion | Low | Medium | No | Near-term | Not started |
| Context-aware question templates | Low | Medium | No | Near-term | **Implemented** (generic; context-aware is the enhancement) |
| CODEX object quality scoring | Low | High | No | Near-term | Not started |
| Graduated analogy scoring | Low | Medium | No | Medium-term | Not started |
| Temporal sequencing validation | Moderate | Medium | No | Medium-term | Not started (constants defined) |
| Analytics / feedback loop | Moderate | High | No | Medium-term | Not started (audit trail data available) |
| Nearest-neighbor fallback for novel situations | Low | Medium | No | Medium-term | **Partial** -- stub exists, matching logic not built |
| NLP preprocessing for unstructured input | Moderate | Medium | Yes (preprocessing only) | Long-term | Not started |
| LLM fallback for novel situations | Moderate | Medium | Yes (fallback only) | Long-term | Not started |
