"""Naive SkillSet implementation (ss-doctrine-naive).

Runs the naive split_pdf + embed_text skills declared in
catalog/doctrine-naive.yaml against the same five doctrine PDFs the moat
SkillSet processes. Writes to the text_chunks projection of
idx-doctrine-naive (Postgres table doctrine_naive_text_chunks).

This is the A/B baseline. Differences from the moat SkillSet:
- Fixed-window chunking (no ADC hierarchy detection)
- No modality classification
- No glossary linkage
- No semantic lifting
- Same embedding model (all-MiniLM-L6-v2, 384-d) so the comparison
  isolates SkillSet + field schema as the only variables.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Callable

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://kd:kd@localhost:5432/kd_platform")

# Skill parameters mirror catalog/doctrine-naive.yaml ss-doctrine-naive.skills:
NAIVE_MAX_TOKENS = 256
NAIVE_OVERLAP_TOKENS = 32


def _word_tokens(text: str) -> list[str]:
    """Rough word-level tokenization for the naive split_pdf skill.

    Real tokenizers exist; this is intentionally simple to make the
    "naive" framing honest.
    """
    return re.findall(r"\S+", text)


def split_pdf_naive(
    pdf_path: Path,
    *,
    max_tokens: int = NAIVE_MAX_TOKENS,
    overlap_tokens: int = NAIVE_OVERLAP_TOKENS,
) -> list[dict[str, Any]]:
    """The naive split_pdf skill: fixed-token windows over plain text.

    Returns a list of chunk dicts with keys:
        chunk_id, content, section_id, source_document, source_uri, chunk_index
    """
    import pdfplumber

    source_document = pdf_path.stem
    source_uri = pdf_path.resolve().as_uri()

    # Extract plain text page-by-page (no hierarchy, no headings)
    text_parts: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
    full_text = "\n".join(text_parts)

    words = _word_tokens(full_text)
    if not words:
        logger.warning("No extractable text in %s", pdf_path)
        return []

    chunks: list[dict[str, Any]] = []
    step = max(1, max_tokens - overlap_tokens)
    chunk_index = 0
    for start in range(0, len(words), step):
        window = words[start : start + max_tokens]
        if not window:
            break
        content = " ".join(window)
        # Synthesized section_id (the naive skill has no real heading detection;
        # bucket chunks by their position-of-N to stand in for "section").
        section_id = f"{source_document}#section-{chunk_index // 10:04d}"
        chunk_id = f"{source_document}#chunk-{chunk_index:05d}"
        chunks.append(
            {
                "chunk_id": chunk_id,
                "content": content,
                "section_id": section_id,
                "source_document": source_document,
                "source_uri": source_uri,
                "chunk_index": chunk_index,
            }
        )
        chunk_index += 1
        if start + max_tokens >= len(words):
            break
    return chunks


def embed_text_naive(chunks: list[dict[str, Any]]) -> list[list[float]]:
    """The naive embed_text skill: all-MiniLM-L6-v2 over chunk content.

    Same model as the moat side; this method only exists to make the
    "this is the embed skill" boundary visible.
    """
    from src.embed import embed_texts

    return embed_texts([c["content"] for c in chunks])


def _upsert_naive_chunks(chunks: list[dict[str, Any]], embeddings: list[list[float]]) -> int:
    """Project skill outputs into doctrine_naive_text_chunks per the YAML selector."""
    if not chunks:
        return 0
    sql = """
        INSERT INTO doctrine_naive_text_chunks
            (chunk_id, section_id, source_uri, source_document, chunk_index, content, content_vector)
        VALUES
            (%(chunk_id)s, %(section_id)s, %(source_uri)s, %(source_document)s,
             %(chunk_index)s, %(content)s, %(content_vector)s)
        ON CONFLICT (chunk_id) DO UPDATE SET
            section_id      = EXCLUDED.section_id,
            source_uri      = EXCLUDED.source_uri,
            source_document = EXCLUDED.source_document,
            chunk_index     = EXCLUDED.chunk_index,
            content         = EXCLUDED.content,
            content_vector  = EXCLUDED.content_vector,
            ingested_at     = now()
    """
    inserted = 0
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            for chunk, emb in zip(chunks, embeddings):
                cur.execute(
                    sql,
                    {
                        **chunk,
                        "content_vector": str(emb),
                    },
                )
                inserted += 1
        conn.commit()
    return inserted


def ingest_naive_pdf(pdf_path: str | Path, *, progress_cb: Callable[[str], None] | None = None) -> int:
    """Run the naive SkillSet end-to-end on a single PDF. Returns row count."""
    p = Path(pdf_path)

    def _emit(msg: str) -> None:
        if progress_cb:
            progress_cb(msg)
        logger.info(msg)

    _emit(f"split_pdf (naive) on {p.name}")
    chunks = split_pdf_naive(p)
    _emit(f"  produced {len(chunks)} chunks ({NAIVE_MAX_TOKENS} tok windows, "
          f"{NAIVE_OVERLAP_TOKENS} tok overlap)")

    _emit(f"embed_text on {len(chunks)} chunks (all-MiniLM-L6-v2, 384-d)")
    embeddings = embed_text_naive(chunks)

    _emit(f"upsert into doctrine_naive_text_chunks")
    n = _upsert_naive_chunks(chunks, embeddings)
    _emit(f"  upserted {n} rows")
    return n


def ingest_naive_corpus(
    blob_uri: str,
    *,
    progress_cb: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run the naive SkillSet over a directory of PDFs.

    `blob_uri` may be a file:// URI or a plain path; for LOCAL mode we
    expect the local data/ directory.
    """
    if blob_uri.startswith("file://"):
        root = Path(blob_uri[len("file://") :])
    else:
        root = Path(blob_uri)

    if not root.exists():
        raise FileNotFoundError(f"Naive corpus root not found: {root}")

    pdfs = sorted(root.glob("*.pdf"))
    if progress_cb:
        progress_cb(f"Found {len(pdfs)} PDFs under {root}")

    stats: dict[str, Any] = {"per_pdf": {}, "total_chunks": 0, "pdf_count": len(pdfs)}
    for pdf in pdfs:
        n = ingest_naive_pdf(pdf, progress_cb=progress_cb)
        stats["per_pdf"][pdf.name] = n
        stats["total_chunks"] += n

    if progress_cb:
        progress_cb(f"Naive SkillSet done: {stats['total_chunks']} chunks across {stats['pdf_count']} PDFs")
    return stats


def get_naive_chunk_count() -> int:
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS cnt FROM doctrine_naive_text_chunks")
            return cur.fetchone()["cnt"]
