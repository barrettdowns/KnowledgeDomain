"""KD Platform Guided Tour -- 7-page Streamlit app (static demo).

Each page maps to a chapter of the Knowledge Domains paper.
This version reads from pre-exported JSON snapshots -- no database,
no embedding model, no API keys required.
"""
import json
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="KD Platform", layout="wide")

DATA = Path(__file__).parent / "data"
PKG = Path(__file__).parent / "doctrine-kd-package"


@st.cache_data
def load_chunks():
    return json.load(open(DATA / "chunks.json"))


@st.cache_data
def load_stats():
    return json.load(open(DATA / "stats.json"))


@st.cache_data
def load_preset_results():
    return json.load(open(DATA / "preset_results.json"))


@st.cache_data
def load_benchmark_results():
    return json.load(open(DATA / "benchmark_results.json"))


@st.cache_data
def load_codex_objects():
    path = DATA / "compiled_codex_objects.json"
    if path.exists():
        return json.load(open(path))
    return []


PAGES = [
    "1. The Problem",
    "2. Atomic Doctrine Chunking (ADC)",
    "3. Semantic Lifting",
    "4. Retrieval",
    "5. CODEX",
    "6. Benchmarks",
    "7. Package",
]

page = st.sidebar.radio("Navigate", PAGES)


# --- PAGE 1: THE PROBLEM ---
if page == PAGES[0]:
    st.title("The Problem")
    st.markdown("""
    **What we are building is a governed, evaluable, reusable semantic layer over
    customer data -- not a vector database.** The raw data platform is government-owned;
    the enrichment layer -- KD schemas, semantic lifting, confidence scores, retrieval
    intelligence -- is commercially licensed IP. This prototype demonstrates what that
    vision looks like as running code.
    """)

    st.markdown("""
    **What we have today:** A single `document_chunks` table with 5 generic columns.
    No hierarchy. No modality classification. No domain metadata.
    A commodity RAG pipeline that treats doctrine the same as a blog post.
    """)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Current System")
        st.code("""document_chunks
  chunk_id
  content
  embedding vector(1024)
  source_filename
  chunk_index""", language="sql")
        st.caption("No domain knowledge. No structure. No authority classification.")

    with col2:
        st.subheader("KD System (this prototype)")
        st.code("""kd_doctrine
  record_id, source_document, classification
  chunk_content, paragraph_id, hierarchy_path
  modality, modality_confidence, modality_signals
  glossary_refs, acronym_refs, document_type
  primary_embedding vector(384)
  warfighting_function, echelon, doctrinal_phase
  + confidence scores, provenance, JSONB overflow""", language="sql")
        st.caption("30+ columns across 5 categories. Every chunk is self-describing.")

    st.info("The Knowledge Domains paper asked: can we do better? This prototype is the answer.")


# --- PAGE 2: ADC ---
elif page == PAGES[1]:
    st.title("Atomic Doctrine Chunking (ADC) -- Structure from Text")
    st.markdown("""
    **ADC is a deterministic chunking algorithm that preserves what generic chunking destroys:**
    document hierarchy, normative authority (is this a requirement or a description?),
    and glossary linkage. Zero LLM calls. Same input, same output, every time. No competitor
    has this capability.
    """)

    stats = load_stats()
    chunks = load_chunks()

    avg_tokens = stats["avg_tokens"]
    hier_pct = round(100 * stats["with_hierarchy"] / max(stats["total"], 1))

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Chunks", f"{stats['total']:,}")
    col2.metric("Documents", stats["doc_count"])
    col3.metric("Avg Tokens/Chunk", f"{avg_tokens:.1f}")
    col4.metric("Hierarchy Coverage", f"{hier_pct}%")

    st.subheader("Modality Distribution")
    st.bar_chart(stats["modality"])
    st.caption("This distribution is a document-level structural signal lost entirely under generic chunking.")

    st.subheader("Browse Chunks")
    for r in chunks[:30]:
        hier = r.get("hierarchy_path", [])
        if isinstance(hier, str):
            hier = json.loads(hier)
        path = " > ".join(hier) if hier else ""
        with st.expander(f"{r['paragraph_id']} | {r['modality']} | {path}"):
            conf = r.get("modality_confidence")
            conf_str = f"{conf:.2f}" if conf is not None else "N/A"
            st.markdown(f"**Modality:** {r['modality']} (confidence: {conf_str})")
            st.markdown(f"**Hierarchy:** {path}")
            st.markdown(f"**Page:** {r.get('page_start', 'N/A')}")
            glossary = r.get("glossary_refs", [])
            if isinstance(glossary, str):
                glossary = json.loads(glossary)
            if glossary:
                st.markdown(f"**Glossary refs:** {', '.join(glossary[:5])}")
            st.text(r.get("chunk_content", "")[:500])

    st.info(f"ADC produced {stats['total']:,} self-describing chunks across {stats['doc_count']} documents. Zero LLM calls. Deterministic. No competitor has this.")


# --- PAGE 3: SEMANTIC LIFTING ---
elif page == PAGES[2]:
    st.title("Semantic Lifting -- Machine Understanding")
    st.markdown("""
    **ADC gives us structure. Semantic lifting gives us meaning.** An LLM reads each chunk
    and extracts domain-specific fields -- warfighting function, echelon, doctrinal phase --
    each with a confidence score. This is the enrichment layer that turns raw text into
    queryable domain intelligence.
    """)

    stats = load_stats()

    st.metric("Chunks Lifted", f"{stats['lifted']}/{stats['total']}")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Warfighting Function")
        st.bar_chart(stats["warfighting_function"])
    with col2:
        st.subheader("Echelon")
        st.bar_chart(stats["echelon"])

    st.subheader("Confidence Distribution")
    confs = stats.get("wf_confidences", [])
    if confs:
        import plotly.express as px
        fig = px.histogram(x=confs, nbins=20, labels={"x": "Confidence", "y": "Count"},
                          title="Warfighting Function Extraction Confidence")
        st.plotly_chart(fig)

    above_08 = sum(1 for c in confs if c >= 0.8)
    st.caption(f"{above_08}/{len(confs)} extractions ({100*above_08/max(len(confs),1):.0f}%) have confidence >= 0.8")

    st.info("Every extracted field carries a confidence score. The system knows how certain it is -- and that certainty is measurable, auditable, and improvable.")


# --- PAGE 4: RETRIEVAL ---
elif page == PAGES[3]:
    st.title("Retrieval -- Ask a Question")

    preset_results = load_preset_results()

    PRESET_QUERIES = {
        "-- Modality filtering advantage --": None,
        "What are the requirements for unified action?": {"suggested_filter": "REQUIREMENT"},
        "What must forces do during combined arms operations?": {"suggested_filter": "REQUIREMENT"},
        "What is the definition of operational art?": {"suggested_filter": "DEFINITION"},
        "-- Cross-document retrieval --": None,
        "What is the intelligence warfighting function?": {"suggested_filter": None},
        "What is cyberspace and how does the Army operate in it?": {"suggested_filter": None},
        "What is the military decision-making process?": {"suggested_filter": None},
        "What are the fundamentals of planning?": {"suggested_filter": "REQUIREMENT"},
        "-- Out-of-scope (no answer expected) --": None,
        "What is the doctrine for naval mine countermeasures?": {"suggested_filter": None},
    }

    preset = st.selectbox("Select a question:", list(PRESET_QUERIES.keys()))

    if preset.startswith("--"):
        query = ""
        st.caption("Select a specific question from the dropdown.")
    else:
        query = preset
        meta = PRESET_QUERIES[preset]
        if meta and meta.get("suggested_filter"):
            st.caption(f"Suggested filter: {meta['suggested_filter']}")

    mode = st.radio("Compare:", ["Raw embeddings only", "ADC (hybrid, no filters)", "Full KD pipeline"],
                    horizontal=True, index=2)

    if query and query in preset_results:
        mode_key = {"Raw embeddings only": "raw", "ADC (hybrid, no filters)": "adc", "Full KD pipeline": "full"}
        results = preset_results[query][mode_key[mode]]
        applied_filter = preset_results[query].get("modality_filter")

        if mode == "Full KD pipeline" and applied_filter:
            st.caption(f"Modality filter applied: **{applied_filter}**")

        total_tokens = sum(len(r.get("chunk_content", "").split()) for r in results)
        st.metric("Results", len(results))
        st.metric("Total tokens retrieved", total_tokens)

        for r in results:
            score = f"{r.get('score', 0):.4f}" if r.get('score') else ""
            hier = r.get("hierarchy_path", [])
            if isinstance(hier, str):
                hier = json.loads(hier)
            path = " > ".join(hier) if hier else ""
            modality = r.get("modality", "")
            para = r.get("paragraph_id", "")

            with st.expander(f"[{score}] {para} | {modality} | {path}"):
                st.markdown(f"**Modality:** {modality}", help="Classified deterministically by ADC at ingest time. No LLM cost, same result every run.")
                if r.get("modality_confidence"):
                    st.markdown(f"**Confidence:** {r['modality_confidence']:.2f}",
                               help="ADC rule engine confidence based on signal density. Scores above 0.8 indicate strong classification.")
                if r.get("warfighting_function"):
                    st.markdown(f"**Warfighting Function:** {r['warfighting_function']}")
                st.text(r.get("chunk_content", "")[:400])

    st.info("The KD pipeline finds the right type of doctrine at the right echelon with measured confidence. Toggle between the three modes above to see the difference.")


# --- PAGE 5: CODEX ---
elif page == PAGES[4]:
    st.title("CODEX -- Structured Evaluation")

    st.markdown("""
    **CODEX is not a chatbot. It is a deterministic, machine-to-machine doctrinal reasoning
    protocol.** Submit a decision artifact, and the rule engine evaluates it against compiled
    doctrine -- returning SUPPORTED, CONDITIONAL, or ABSTAIN with specific trust and caution
    factors. When information is missing, CODEX tells you exactly what it needs and why.
    Same inputs always produce the same outputs. No LLM in the evaluation path.
    """)

    col1, col2 = st.columns(2)
    with col1:
        objective = st.text_area("Objective:", "Develop courses of action for brigade offensive operation")
        mission_type = st.text_input("Mission type:", "military_decision_making_process")
        echelon = st.text_input("Echelon:", "brigade")
    with col2:
        phase = st.text_input("Phase:", "")
        observations = st.text_area("Observations (one per line):", "commander guidance issued")
        actions = st.text_area("Proposed actions (one per line):", "conduct war game")
    st.caption("This starts sparse — you'll get CONDITIONAL with caution factors. Add observations like 'COA statement and sketch prepared' and 'critical events identified' to watch the evaluation shift toward SUPPORTED.")

    if st.button("Evaluate"):
        obs_list = [o.strip() for o in observations.split("\n") if o.strip()]
        act_list = [a.strip() for a in actions.split("\n") if a.strip()]

        codex_objects = load_codex_objects()

        def score_relevance(obj, context):
            score = 0.0
            ce = obj.get("context_envelope", {})
            if context.get("mission_type") and ce.get("mission_type"):
                if context["mission_type"].lower() in ce["mission_type"].lower():
                    score += 3.0
                elif any(w in ce["mission_type"].lower() for w in context["mission_type"].lower().split("_")):
                    score += 1.5
            if context.get("echelon") and ce.get("echelon"):
                if context["echelon"].lower() == ce["echelon"].lower():
                    score += 2.0
                elif context["echelon"].lower() in ce["echelon"].lower():
                    score += 1.0
            if context.get("phase") and ce.get("phase"):
                if context["phase"].lower() in ce["phase"].lower():
                    score += 1.5
            for trigger in obj.get("triggers", []):
                trigger_words = set(trigger.lower().replace("_", " ").split())
                obj_words = set(context.get("objective", "").lower().split())
                if len(trigger_words & obj_words) >= max(1, len(trigger_words) * 0.3):
                    score += 1.0
            return score

        context = {"mission_type": mission_type, "echelon": echelon,
                    "phase": phase, "objective": objective}
        scored = [(score_relevance(obj, context), obj) for obj in codex_objects]
        scored.sort(key=lambda x: x[0], reverse=True)
        matched = [obj for s, obj in scored[:3] if s > 0]

        if not matched:
            result = {"evaluation": "ABSTAIN", "abstain_reason": "no_doctrinal_coverage",
                      "recommendation": "No compiled doctrine covers this scenario."}
        else:
            primary = matched[0]
            ce = primary.get("context_envelope", {})
            evidence_tokens = set()
            for o in obs_list:
                evidence_tokens.update(o.lower().split())
            for a in act_list:
                evidence_tokens.update(a.lower().split())

            trust_factors, caution_factors = [], []
            for chain in primary.get("causal_chains", []):
                chain_ok = True
                for link in chain.get("links", []):
                    cond_tokens = set(link.get("condition", "").lower().split())
                    if len(cond_tokens & evidence_tokens) < max(1, len(cond_tokens) * 0.3):
                        chain_ok = False
                        caution_factors.append(f"Causal chain '{chain.get('pattern_name', '?')}' broken at '{link.get('condition', '?')}'")
                        break
                if chain_ok:
                    trust_factors.append(f"Causal chain '{chain.get('pattern_name', '?')}' fully satisfied")

            if caution_factors:
                evaluation = "CONDITIONAL"
                recommendation = "Review caution factors before execution."
            elif not trust_factors:
                evaluation = "CONDITIONAL"
                recommendation = "Insufficient evidence to fully validate."
            else:
                evaluation = "SUPPORTED"
                recommendation = "All evaluated causal chains satisfied."

            questions = []
            q_id = 1
            if len(obs_list) < 2:
                questions.append({"id": f"q{q_id}", "question": "What is the composition and strength of friendly forces?", "reason_needed": "Force composition determines viable doctrinal options"})
                q_id += 1
                questions.append({"id": f"q{q_id}", "question": "What is the known or estimated enemy composition and disposition?", "reason_needed": "Enemy assessment drives course of action development"})
                q_id += 1
            if not echelon or not phase or not mission_type:
                questions.append({"id": f"q{q_id}", "question": "What echelon, phase, and mission type does this request apply to?", "reason_needed": "Context envelope scopes which doctrinal reasoning applies"})
                q_id += 1
            for obs in primary.get("required_observations", []):
                if obs.lower() not in {o.lower() for o in obs_list}:
                    questions.append({"id": f"q{q_id}", "question": f"Has the following been observed/confirmed: {obs.replace('_', ' ')}?", "reason_needed": "Required observation for doctrinal evaluation"})
                    q_id += 1

            result = {
                "evaluation": evaluation, "doctrine_coverage": "ANALOGOUS",
                "trust_factors": trust_factors, "caution_factors": caution_factors,
                "recommendation": recommendation,
                "guidance_actions": [a.get("action", "") for a in primary.get("allowed_actions", [])[:5]],
                "constraints": primary.get("constraints", [])[:5],
                "clarification_questions": questions[:5],
            }

        eval_type = result.get("evaluation", "?")
        if eval_type == "SUPPORTED":
            st.success(f"Evaluation: {eval_type}")
        elif eval_type == "CONDITIONAL":
            st.warning(f"Evaluation: {eval_type}")
        elif eval_type == "ABSTAIN":
            st.error(f"Evaluation: {eval_type}")
        else:
            st.info(f"Evaluation: {eval_type}")

        if result.get("doctrine_coverage"):
            st.markdown(f"**Coverage:** {result['doctrine_coverage']}")

        if result.get("trust_factors"):
            st.markdown("**Trust Factors:**")
            for tf in result["trust_factors"]:
                st.markdown(f"- {tf}", help="This causal chain was fully satisfied: every IF/THEN link was evidenced in your artifact.")

        if result.get("caution_factors"):
            st.markdown("**Caution Factors:**")
            for cf in result["caution_factors"]:
                st.markdown(f"- {cf}", help="This link broke because the condition was not found in your submitted observations.")

        if result.get("recommendation"):
            st.markdown(f"**Recommendation:** {result['recommendation']}")

        if result.get("guidance_actions"):
            st.markdown("**Doctrine-Guided Actions:**")
            for a in result["guidance_actions"]:
                st.markdown(f"- {a}")

        if result.get("constraints"):
            st.markdown("**Constraints:**")
            for c in result["constraints"]:
                st.markdown(f"- {c}")

        if result.get("clarification_questions"):
            st.divider()
            st.subheader("What CODEX Still Needs to Know")
            st.caption("The system identifies exactly what information is missing for a complete evaluation.")
            for q in result["clarification_questions"]:
                st.markdown(f"**{q['question']}**")
                st.caption(f"Why: {q['reason_needed']}")

    st.info("Deterministic. Auditable. Edge-deployable. Same inputs, same outputs, every time. No competitor has built this.")


# --- PAGE 6: BENCHMARKS ---
elif page == PAGES[5]:
    st.title("Benchmarks -- Prove It Works")

    results = load_benchmark_results()

    st.subheader("NDCG@10 Comparison")
    ndcg_data = {k: v["ndcg_10"] for k, v in results.items()}
    st.bar_chart(ndcg_data)

    st.subheader("All Metrics")
    import pandas as pd
    df = pd.DataFrame(results).T
    df.columns = ["NDCG@10", "MRR", "Precision@5"]
    st.dataframe(df.style.format("{:.4f}"))

    st.markdown("""
    **Key finding:** With a 5-document, 2,910-chunk corpus, the full pipeline shows
    that metadata filtering provides precision control. The MRR advantage of the full
    pipeline (0.31 vs 0.27) indicates the right answer appears earlier when taxonomy
    filters are applied. With production embeddings (text-embedding-3-large at 1024 dims)
    and a larger benchmark set, the quality gap widens.
    """)

    st.info("Benchmarks are the hardest capability for any competitor to replicate. They require a working domain system AND willing analysts. This is the measurement infrastructure that proves the system works.")


# --- PAGE 7: PACKAGE ---
elif page == PAGES[6]:
    st.title("Package")

    st.markdown("""
    The entire Knowledge Domain -- schema, chunking config, lifting prompts,
    retrieval config, benchmark results -- exports as a portable package.
    """)

    st.subheader("Package Contents")
    st.code("""doctrine-kd-package/
  V001__create_kd_doctrine.sql    # Schema migration
  doctrine.yaml                   # KD manifest
  doctrine_qa.json                # Benchmark Q/A set
  kd_manifest.json                # Package metadata""")

    manifest_path = PKG / "kd_manifest.json"
    if manifest_path.exists():
        manifest = json.load(open(manifest_path))
        st.subheader("Manifest")
        st.json(manifest)
    else:
        st.caption("Package manifest not found.")

    st.divider()
    st.subheader("Why This Package Matters")
    st.markdown("""
    This package is what makes the moat compound. Customer 1's KD deploys to Customer 2
    in days -- because the schema, chunking, lifting, and retrieval are pre-built and the
    benchmarks prove they work. Customer 2's analysts add questions to the benchmark corpus.
    The corpus grows. Customer 3 is faster than Customer 2. The prototype you just walked
    through is the first turn of that flywheel.
    """)

    st.info("This entire KD exports as a portable artifact. Schema, chunking, lifting, retrieval, benchmarks -- everything needed to stand up a new Knowledge Domain.")
