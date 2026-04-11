"""Benchmark runner: evaluate retrieval quality against a Q/A dataset."""
import json
import math
import logging
from pathlib import Path

from src.retrieve import retrieve, retrieve_raw, retrieve_boosted
from src.db import get_connection

logger = logging.getLogger(__name__)


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


def run_benchmark(qa_path: str = "benchmarks/doctrine_qa.json") -> dict:
    """Run benchmark against the Q/A dataset. Returns aggregate scores."""
    qa_data = json.loads(Path(qa_path).read_text())
    questions = qa_data["questions"]

    results = {"full_pipeline": [], "adc_only": [], "raw_embedding": []}

    for q in questions:
        relevant = resolve_paragraph_ids(q["expected_paragraph_ids"], q.get("source_document"))
        if not relevant:
            logger.warning(f"No matching records for question: {q['query'][:60]}")
            continue

        filters = q.get("filters", {})

        # Full pipeline: tuned hybrid search (alpha=0.80) with modality boost
        modality_boost = filters.get("modality") if filters else None
        full_results = retrieve_boosted(q["query"], top_k=10, alpha=0.80, modality_boost=modality_boost, boost_weight=0.05)
        full_ids = [str(r["record_id"]) for r in full_results]

        # ADC only: hybrid search, no taxonomy filters
        adc_results = retrieve(q["query"], top_k=10)
        adc_ids = [str(r["record_id"]) for r in adc_results]

        # Raw embedding: vector-only, no metadata
        raw_results = retrieve_raw(q["query"], top_k=10)
        raw_ids = [str(r["record_id"]) for r in raw_results]

        for name, ids in [("full_pipeline", full_ids), ("adc_only", adc_ids), ("raw_embedding", raw_ids)]:
            results[name].append({
                "query": q["query"],
                "ndcg_10": ndcg_at_k(ids, relevant, 10),
                "mrr": mrr(ids, relevant),
                "precision_5": precision_at_k(ids, relevant, 5),
            })

    summary = {}
    for name, scores in results.items():
        if not scores:
            continue
        summary[name] = {
            "ndcg_10": sum(s["ndcg_10"] for s in scores) / len(scores),
            "mrr": sum(s["mrr"] for s in scores) / len(scores),
            "precision_5": sum(s["precision_5"] for s in scores) / len(scores),
            "question_count": len(scores),
        }

    return {"summary": summary, "per_question": results}
