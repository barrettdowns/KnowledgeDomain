"""Hybrid retrieval: vector similarity + lexical search with metadata filtering."""
import json
import logging
from src.embed import embed_query
from src.db import get_connection

logger = logging.getLogger(__name__)


def retrieve(
    query: str,
    top_k: int = 10,
    alpha: float = 0.7,
    filters: dict = None,
    min_confidence: float = 0.0,
) -> list[dict]:
    """
    Hybrid search: alpha * cosine_similarity + (1-alpha) * ts_rank_cd.
    Applies metadata filters (modality, warfighting_function, echelon, etc.)
    and confidence thresholds on lifted fields.
    """
    query_embedding = embed_query(query)

    where_clauses = []
    params = {
        "query_embedding": str(query_embedding),
        "query_text": query,
        "top_k": top_k,
        "alpha": alpha,
    }

    if filters:
        for field, value in filters.items():
            safe_field = field.replace("'", "").replace(";", "")
            param_name = f"filter_{safe_field}"
            where_clauses.append(f"{safe_field} = %({param_name})s")
            params[param_name] = value

    if min_confidence > 0:
        where_clauses.append(
            "(warfighting_function_confidence >= %(min_conf)s "
            "OR warfighting_function IS NULL)"
        )
        params["min_conf"] = min_confidence

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    sql = f"""
        SELECT
            record_id, chunk_content, paragraph_id, hierarchy_path,
            modality, modality_confidence, modality_signals,
            glossary_refs, acronym_refs, document_type,
            page_start, page_end, source_document,
            warfighting_function, warfighting_function_confidence,
            echelon, echelon_confidence,
            doctrinal_phase, doctrinal_phase_confidence,
            (
                %(alpha)s * (1 - (primary_embedding <=> %(query_embedding)s))
                + (1 - %(alpha)s) * ts_rank_cd(content_fts, plainto_tsquery('english', %(query_text)s))
            ) AS score
        FROM kd_doctrine
        {where_sql}
        ORDER BY score DESC
        LIMIT %(top_k)s
    """

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            results = cur.fetchall()
    finally:
        conn.close()

    return results


def retrieve_raw(query: str, top_k: int = 10) -> list[dict]:
    """Raw embedding-only search with no metadata. Simulates a generic RAG pipeline."""
    query_embedding = embed_query(query)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT record_id, chunk_content, paragraph_id,
                       (1 - (primary_embedding <=> %(emb)s)) AS score
                FROM kd_doctrine
                ORDER BY primary_embedding <=> %(emb)s
                LIMIT %(top_k)s
            """, {"emb": str(query_embedding), "top_k": top_k})
            return cur.fetchall()
    finally:
        conn.close()
