#!/usr/bin/env python
"""Phase 6 mapping: moat-side paragraph_id  →  naive-side chunk_id(s).

For each ground-truth paragraph in benchmarks/doctrine_qa.json, find the
naive-projection chunk(s) in doctrine_naive_text_chunks that best cover
the same content span. The resulting map lets Page 6 evaluate the naive
SkillSet against the same Q/A set without re-curating a separate ground
truth.

Strategy:
  1. Fetch each ground-truth paragraph's text from kd_doctrine.
  2. Restrict candidates to naive chunks in the same source_document
     (after normalizing 'ADP 3-0' <-> 'ADP_3-0').
  3. Score each candidate by token-set overlap (Jaccard on lowercased
     word 4-grams). Take the top-K that exceed the threshold.

The naive 256-token windows are larger than moat paragraphs, so a single
moat paragraph usually maps to 1-2 naive chunks. We keep up to top_k=3
matches above min_overlap=0.05.

Output: benchmarks/doctrine_qa_naive_map.json
  {
    "metadata": {...},
    "mapping": {
      "<paragraph_id>|<source_document_moat>": {
        "moat_paragraph_id": "...",
        "source_document_moat": "ADP 3-0",
        "source_document_naive": "ADP_3-0",
        "moat_text_preview": "...",
        "naive_matches": [
          {"chunk_id": "ADP_3-0#chunk-00012", "score": 0.31, "preview": "..."},
          ...
        ]
      }
    }
  }
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("map-paragraph-to-naive")

import os
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://kd:kd@localhost:5432/kd_platform")

QA_PATH = Path("benchmarks/doctrine_qa.json")
OUT_PATH = Path("benchmarks/doctrine_qa_naive_map.json")

TOP_K_NAIVE_PER_PARAGRAPH = 3
MIN_OVERLAP_SCORE = 0.05  # very permissive; naive chunks are 5-10x larger than moat paragraphs


_token_re = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    return _token_re.findall((text or "").lower())


def ngrams(toks: list[str], n: int = 4) -> set[tuple[str, ...]]:
    if len(toks) < n:
        return {tuple(toks)} if toks else set()
    return {tuple(toks[i : i + n]) for i in range(len(toks) - n + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = a & b
    union = a | b
    return len(inter) / len(union)


def normalize_doc_name(moat_name: str) -> str:
    """'ADP 3-0' -> 'ADP_3-0' (the naive side uses pdf.stem)."""
    return moat_name.replace(" ", "_")


def collect_ground_truth_paragraphs(qa_path: Path) -> list[tuple[str, str]]:
    """Return unique (paragraph_id, source_document_moat) pairs across the Q/A set."""
    data = json.loads(qa_path.read_text())
    seen: set[tuple[str, str]] = set()
    for q in data["questions"]:
        src = q.get("source_document") or ""
        for pid in q.get("expected_paragraph_ids", []):
            seen.add((pid, src))
    return sorted(seen)


def fetch_moat_paragraph(cur, paragraph_id: str, source_document: str) -> dict | None:
    cur.execute(
        """SELECT paragraph_id, source_document, chunk_content
           FROM kd_doctrine
           WHERE paragraph_id = %s AND source_document = %s
           LIMIT 1""",
        (paragraph_id, source_document),
    )
    return cur.fetchone()


def fetch_naive_chunks_for_document(cur, source_document_naive: str) -> list[dict]:
    cur.execute(
        """SELECT chunk_id, section_id, content
           FROM doctrine_naive_text_chunks
           WHERE source_document = %s
           ORDER BY chunk_index""",
        (source_document_naive,),
    )
    return cur.fetchall()


def main() -> None:
    pairs = collect_ground_truth_paragraphs(QA_PATH)
    log.info("Found %d unique (paragraph_id, source_document) ground-truth pairs", len(pairs))

    mapping: dict[str, dict] = {}
    unmatched: list[str] = []
    miss_in_moat: list[str] = []
    naive_chunks_cache: dict[str, list[dict]] = {}

    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            for paragraph_id, source_doc_moat in pairs:
                key = f"{paragraph_id}|{source_doc_moat}"

                # 1. Look up the moat paragraph text
                moat = fetch_moat_paragraph(cur, paragraph_id, source_doc_moat)
                if not moat:
                    miss_in_moat.append(key)
                    log.warning("Moat paragraph not found: %s", key)
                    continue
                moat_text = moat["chunk_content"]
                moat_ngrams = ngrams(tokens(moat_text), n=4)

                # 2. Pull candidate naive chunks from the same document (cached)
                source_doc_naive = normalize_doc_name(source_doc_moat)
                if source_doc_naive not in naive_chunks_cache:
                    naive_chunks_cache[source_doc_naive] = fetch_naive_chunks_for_document(cur, source_doc_naive)
                candidates = naive_chunks_cache[source_doc_naive]

                # 3. Score by 4-gram Jaccard
                scored: list[tuple[float, dict]] = []
                for cand in candidates:
                    cand_ngrams = ngrams(tokens(cand["content"]), n=4)
                    s = jaccard(moat_ngrams, cand_ngrams)
                    if s >= MIN_OVERLAP_SCORE:
                        scored.append((s, cand))

                scored.sort(key=lambda x: x[0], reverse=True)
                top = scored[:TOP_K_NAIVE_PER_PARAGRAPH]

                if not top:
                    unmatched.append(key)
                    log.warning("No naive matches for %s (best below threshold)", key)
                else:
                    log.info(
                        "  %s -> %d naive chunk(s), top score %.3f",
                        key, len(top), top[0][0],
                    )

                mapping[key] = {
                    "moat_paragraph_id": paragraph_id,
                    "source_document_moat": source_doc_moat,
                    "source_document_naive": source_doc_naive,
                    "moat_text_preview": moat_text[:160].replace("\n", " "),
                    "naive_matches": [
                        {
                            "chunk_id": c["chunk_id"],
                            "score": round(float(s), 4),
                            "preview": c["content"][:160].replace("\n", " "),
                        }
                        for s, c in top
                    ],
                }

    out = {
        "metadata": {
            "kd_name": "doctrine",
            "version": "1.0",
            "source_qa": str(QA_PATH),
            "strategy": "ngram_jaccard",
            "ngram_n": 4,
            "top_k": TOP_K_NAIVE_PER_PARAGRAPH,
            "min_overlap_score": MIN_OVERLAP_SCORE,
        },
        "stats": {
            "ground_truth_pairs": len(pairs),
            "mapped": len(pairs) - len(unmatched) - len(miss_in_moat),
            "unmatched_no_naive_above_threshold": len(unmatched),
            "missing_in_moat": len(miss_in_moat),
            "unmatched_pairs": unmatched,
            "missing_in_moat_pairs": miss_in_moat,
        },
        "mapping": mapping,
    }
    OUT_PATH.write_text(json.dumps(out, indent=2))
    log.info("Wrote mapping to %s", OUT_PATH)
    log.info(
        "Stats: %d ground-truth pairs, %d mapped, %d unmatched, %d missing-in-moat",
        len(pairs), out["stats"]["mapped"], out["stats"]["unmatched_no_naive_above_threshold"],
        out["stats"]["missing_in_moat"],
    )


if __name__ == "__main__":
    main()
