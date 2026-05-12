"""Benchmark runner: evaluate retrieval quality against a Q/A dataset.

Modes evaluated (post-Phase-6):

Phase-5-aligned columns (these match Page 4's four-column A/B headers):
    naive_vector      -- vector-only over doctrine_naive_text_chunks
    naive_hybrid      -- hybrid over doctrine_naive_text_chunks
    moat_hybrid       -- hybrid over kd_doctrine (no filters, no boost)
    moat_filtered     -- hybrid over kd_doctrine + modality filter + min_confidence

Legacy columns (kept for backwards-compat with earlier README numbers):
    raw_embedding     -- moat-side vector-only (no metadata)
    adc_only          -- alias for moat_hybrid
    full_pipeline     -- moat hybrid with modality_boost (soft) at alpha=0.80

The naive_* modes are evaluated against ground truth derived from
benchmarks/doctrine_qa_naive_map.json (paragraph_id -> [naive chunk_id]).
All moat_* modes use the original benchmarks/doctrine_qa.json paragraph
ground truth resolved to kd_doctrine.record_id.
"""
import json
import math
import logging
from pathlib import Path

from src.retrieve import retrieve, retrieve_raw, retrieve_boosted
from src.retrieve_naive import query_naive_text, query_naive_hybrid
from src.db import get_connection

logger = logging.getLogger(__name__)

DEFAULT_NAIVE_MAP_PATH = "benchmarks/doctrine_qa_naive_map.json"
DEFAULT_MIN_CONFIDENCE = 0.7

# Headers shown on Page 6, in order. Keep these in sync with Page 4.
PHASE5_COLUMN_ORDER = ["naive_vector", "naive_hybrid", "moat_hybrid", "moat_filtered"]
PHASE5_COLUMN_LABELS = {
    "naive_vector": "naive SkillSet · text_chunks",
    "naive_hybrid": "naive + hybrid",
    "moat_hybrid": "moat SkillSet · text_chunks",
    "moat_filtered": "moat + modality filter + confidence",
}
LEGACY_COLUMN_ORDER = ["raw_embedding", "adc_only", "full_pipeline"]
LEGACY_COLUMN_LABELS = {
    "raw_embedding": "Raw embeddings (moat side, vector-only)",
    "adc_only": "ADC hybrid (moat side)",
    "full_pipeline": "Full pipeline (moat + modality boost)",
}


def dcg_at_k(retrieved_ids: list[str], relevant: dict[str, int], k: int) -> float:
    score = 0.0
    for i, rid in enumerate(retrieved_ids[:k]):
        rel = relevant.get(rid, 0)
        if rel > 0:
            score += rel / math.log2(i + 2)
    return score


def ndcg_at_k(retrieved_ids: list[str], relevant: dict[str, int], k: int = 10) -> float:
    actual = dcg_at_k(retrieved_ids, relevant, k)
    ideal_ids = sorted(relevant.keys(), key=lambda x: relevant[x], reverse=True)[:k]
    ideal = dcg_at_k(ideal_ids, relevant, k)
    if ideal == 0:
        return 0.0
    return actual / ideal


def mrr(retrieved_ids: list[str], relevant: dict[str, int]) -> float:
    for i, rid in enumerate(retrieved_ids):
        if relevant.get(rid, 0) > 0:
            return 1.0 / (i + 1)
    return 0.0


def precision_at_k(retrieved_ids: list[str], relevant: dict[str, int], k: int) -> float:
    top_k = retrieved_ids[:k]
    if not top_k:
        return 0.0
    return sum(1 for r in top_k if relevant.get(r, 0) > 0) / len(top_k)


def resolve_paragraph_ids(paragraph_ids: list[str], source_document: str = None) -> dict[str, int]:
    """Resolve paragraph IDs to record IDs with relevance scores.
    When source_document is specified, only match paragraphs from that document."""
    if not paragraph_ids:
        return {}
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            placeholders = ", ".join(["%s"] * len(paragraph_ids))
            if source_document:
                cur.execute(
                    f"SELECT record_id, paragraph_id FROM kd_doctrine WHERE paragraph_id IN ({placeholders}) AND source_document = %s",
                    paragraph_ids + [source_document]
                )
            else:
                cur.execute(
                    f"SELECT record_id, paragraph_id FROM kd_doctrine WHERE paragraph_id IN ({placeholders})",
                    paragraph_ids
                )
            rows = cur.fetchall()
            relevance = {}
            for i, pid in enumerate(paragraph_ids):
                for row in rows:
                    if row["paragraph_id"] == pid:
                        relevance[str(row["record_id"])] = len(paragraph_ids) - i
            return relevance
    finally:
        conn.close()


def resolve_naive_chunk_ids(
    paragraph_ids: list[str],
    source_document: str | None,
    naive_map: dict,
) -> dict[str, int]:
    """Project the moat-side ground-truth paragraph_ids onto naive chunk_ids.

    For each paragraph_id, look up its mapped naive chunk_ids (from
    benchmarks/doctrine_qa_naive_map.json, keyed by '<paragraph_id>|<source_document>')
    and produce a relevance dict {naive_chunk_id: rel_score}. Relevance follows
    the same descending-rank convention as resolve_paragraph_ids().
    """
    if not paragraph_ids:
        return {}
    relevance: dict[str, int] = {}
    n = len(paragraph_ids)
    for i, pid in enumerate(paragraph_ids):
        # Prefer the (pid, source_document) entry; fall back to "<pid>|<any>" matches.
        key = f"{pid}|{source_document or ''}"
        entry = naive_map.get(key)
        if not entry:
            # Try to find a key with the same paragraph_id under any source_document
            for k in naive_map:
                if k.startswith(f"{pid}|"):
                    entry = naive_map[k]
                    break
        if not entry:
            continue
        rel_score = n - i  # same convention as resolve_paragraph_ids
        for match in entry.get("naive_matches", []):
            cid = match["chunk_id"]
            # If a naive chunk is mapped from multiple ground-truth paragraphs,
            # keep the max relevance (the paragraph that ranked highest).
            relevance[cid] = max(relevance.get(cid, 0), rel_score)
    return relevance


def _load_naive_map(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        logger.warning("Naive map not found at %s; naive_* modes will return zero hits", p)
        return {}
    return json.loads(p.read_text()).get("mapping", {})


def run_benchmark(
    qa_path: str = "benchmarks/doctrine_qa.json",
    naive_map_path: str = DEFAULT_NAIVE_MAP_PATH,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    top_k: int = 10,
) -> dict:
    """Evaluate retrieval quality across all configured modes.

    Returns a dict with:
        summary: {mode_name: {ndcg_10, mrr, precision_5, question_count}}
        per_question: {mode_name: [{query, ndcg_10, mrr, precision_5}, ...]}
        config: {min_confidence, top_k, naive_map_path, ...}
    """
    qa_data = json.loads(Path(qa_path).read_text())
    questions = qa_data["questions"]
    naive_map = _load_naive_map(naive_map_path)

    all_modes = PHASE5_COLUMN_ORDER + LEGACY_COLUMN_ORDER
    results: dict[str, list[dict]] = {m: [] for m in all_modes}

    for q in questions:
        # Moat-side ground truth (paragraph_id -> record_id)
        moat_relevant = resolve_paragraph_ids(q["expected_paragraph_ids"], q.get("source_document"))
        # Naive-side ground truth (paragraph_id -> [naive chunk_id])
        naive_relevant = resolve_naive_chunk_ids(
            q["expected_paragraph_ids"], q.get("source_document"), naive_map
        )

        if not moat_relevant and not naive_relevant:
            logger.warning(f"No matching records for question: {q['query'][:60]}")
            continue

        filters = q.get("filters", {})
        modality_filter = filters.get("modality") if filters else None

        # --- Phase 5-aligned columns ---
        # Column 1: naive_vector — vector-only over doctrine_naive_text_chunks
        nv = query_naive_text(q["query"], top_k=top_k)
        nv_ids = [h["chunk_id"] for h in nv]

        # Column 2: naive_hybrid — hybrid over doctrine_naive_text_chunks
        nh = query_naive_hybrid(q["query"], top_k=top_k)
        nh_ids = [h["chunk_id"] for h in nh]

        # Column 3: moat_hybrid — hybrid over kd_doctrine, no filters
        mh = retrieve(q["query"], top_k=top_k)
        mh_ids = [str(r["record_id"]) for r in mh]

        # Column 4: moat_filtered — hybrid + modality filter + min_confidence
        if modality_filter:
            mf = retrieve(
                q["query"],
                top_k=top_k,
                filters={"modality": modality_filter},
                min_confidence=min_confidence,
            )
        else:
            mf = retrieve(q["query"], top_k=top_k, min_confidence=min_confidence)
        mf_ids = [str(r["record_id"]) for r in mf]

        # --- Legacy columns (preserved for README continuity) ---
        # full_pipeline: moat hybrid with soft modality boost at alpha=0.80
        fp = retrieve_boosted(
            q["query"], top_k=top_k, alpha=0.80,
            modality_boost=modality_filter, boost_weight=0.05,
        )
        fp_ids = [str(r["record_id"]) for r in fp]
        # adc_only: alias for moat_hybrid (kept so old summary keys still resolve)
        ao_ids = mh_ids
        # raw_embedding: moat vector-only
        re_ = retrieve_raw(q["query"], top_k=top_k)
        re_ids = [str(r["record_id"]) for r in re_]

        per_mode = {
            "naive_vector":  (nv_ids, naive_relevant),
            "naive_hybrid":  (nh_ids, naive_relevant),
            "moat_hybrid":   (mh_ids, moat_relevant),
            "moat_filtered": (mf_ids, moat_relevant),
            "full_pipeline": (fp_ids, moat_relevant),
            "adc_only":      (ao_ids, moat_relevant),
            "raw_embedding": (re_ids, moat_relevant),
        }
        for name, (ids, rel) in per_mode.items():
            if not rel:
                # Skip this question for this mode if there's no ground truth on that side
                continue
            results[name].append({
                "query": q["query"],
                "ndcg_10": ndcg_at_k(ids, rel, 10),
                "mrr": mrr(ids, rel),
                "precision_5": precision_at_k(ids, rel, 5),
            })

    summary: dict[str, dict] = {}
    for name, scores in results.items():
        if not scores:
            continue
        summary[name] = {
            "ndcg_10":         sum(s["ndcg_10"] for s in scores) / len(scores),
            "mrr":             sum(s["mrr"] for s in scores) / len(scores),
            "precision_5":     sum(s["precision_5"] for s in scores) / len(scores),
            "question_count":  len(scores),
        }

    return {
        "summary": summary,
        "per_question": results,
        "config": {
            "qa_path": qa_path,
            "naive_map_path": naive_map_path,
            "min_confidence": min_confidence,
            "top_k": top_k,
            "phase5_column_order": PHASE5_COLUMN_ORDER,
            "phase5_column_labels": PHASE5_COLUMN_LABELS,
            "legacy_column_order": LEGACY_COLUMN_ORDER,
            "legacy_column_labels": LEGACY_COLUMN_LABELS,
        },
    }
