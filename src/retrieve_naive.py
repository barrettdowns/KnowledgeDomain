"""Naive Index retrieval (idx-doctrine-naive / text_chunks projection).

Two retrieval modes, both producing hits in the standard shape from
RFC-0001 §1.6.3:

    query_naive_text(query, top_k)   -- pure cosine (vector-only)
    query_naive_hybrid(query, top_k) -- cosine + ts_rank_cd blended by
                                        the projection's hybrid_retrieval
                                        config (vector_weight: 0.6 /
                                        keyword_weight: 0.4 per
                                        catalog/doctrine-naive.yaml)

These are the LOCAL-mode equivalents of:
    POST /kd/knowledge-bases/kb-doctrine-naive/query
         { "query": "...", "projection_kinds": ["text"],
           "include_siblings": false }
"""
from __future__ import annotations

import os
import logging
from typing import Any

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

from src.embed import embed_query

load_dotenv()
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://kd:kd@localhost:5432/kd_platform")

# Defaults that mirror the projection's hybrid_retrieval block.
DEFAULT_VECTOR_WEIGHT = 0.6
DEFAULT_KEYWORD_WEIGHT = 0.4


def _row_to_hit(row: dict[str, Any], score: float) -> dict[str, Any]:
    """Coerce a DB row into RFC-0001 §1.6.3 standard hit shape."""
    return {
        "chunk_id": row["chunk_id"],
        "score": float(score),
        "content": row["content"],
        "projection": "text_chunks",
        "metadata": {
            "section_id": row.get("section_id"),
            "source_uri": row.get("source_uri"),
            "source_document": row.get("source_document"),
            "chunk_index": row.get("chunk_index"),
        },
        "siblings": [],
        # Convenience pass-through for legacy ui.py code paths:
        "section_id": row.get("section_id"),
        "source_document": row.get("source_document"),
        "chunk_content": row["content"],
    }


def query_naive_text(query: str, top_k: int = 10) -> list[dict[str, Any]]:
    """Pure cosine retrieval over doctrine_naive_text_chunks."""
    emb = embed_query(query)
    sql = """
        SELECT
            chunk_id, section_id, source_uri, source_document, chunk_index,
            content,
            1 - (content_vector <=> %(emb)s::vector) AS score
        FROM doctrine_naive_text_chunks
        ORDER BY content_vector <=> %(emb)s::vector
        LIMIT %(top_k)s
    """
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"emb": str(emb), "top_k": top_k})
            rows = cur.fetchall()
    return [_row_to_hit(r, r["score"]) for r in rows]


def query_naive_hybrid(
    query: str,
    top_k: int = 10,
    vector_weight: float = DEFAULT_VECTOR_WEIGHT,
    keyword_weight: float = DEFAULT_KEYWORD_WEIGHT,
) -> list[dict[str, Any]]:
    """Hybrid retrieval: vector cosine + lexical ts_rank_cd, blended.

    Matches the projection's hybrid_retrieval config in
    catalog/doctrine-naive.yaml. Weights normalize to 1.0 for the
    final score so the column header on Page 4 can show a directly
    comparable number against the moat-side hybrid.
    """
    emb = embed_query(query)
    sql = """
        SELECT
            chunk_id, section_id, source_uri, source_document, chunk_index,
            content,
            (
                %(vw)s * (1 - (content_vector <=> %(emb)s::vector))
                + %(kw)s * (
                    ts_rank_cd(content_fts, plainto_tsquery('english', %(q)s))
                    / (1 + ts_rank_cd(content_fts, plainto_tsquery('english', %(q)s)))
                  )
            ) AS score
        FROM doctrine_naive_text_chunks
        ORDER BY score DESC
        LIMIT %(top_k)s
    """
    total_w = vector_weight + keyword_weight
    vw = vector_weight / total_w if total_w > 0 else 0.5
    kw = keyword_weight / total_w if total_w > 0 else 0.5
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"emb": str(emb), "q": query, "vw": vw, "kw": kw, "top_k": top_k})
            rows = cur.fetchall()
    return [_row_to_hit(r, r["score"]) for r in rows]
