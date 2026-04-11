"""Database connection and query helpers for kd_doctrine."""
import os
import json
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://kd:kd@localhost:5432/kd_platform")


def get_connection():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def insert_chunks(chunks: list[dict]) -> int:
    """Batch insert ADC chunks with embeddings into kd_doctrine. Returns row count."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for chunk in chunks:
                cur.execute("""
                    INSERT INTO kd_doctrine (
                        source_document, classification, chunk_content, paragraph_id,
                        hierarchy_path, modality, modality_confidence, modality_signals,
                        glossary_refs, acronym_refs, document_type, page_start, page_end,
                        primary_embedding
                    ) VALUES (
                        %(source_document)s, %(classification)s, %(chunk_content)s,
                        %(paragraph_id)s, %(hierarchy_path)s, %(modality)s,
                        %(modality_confidence)s, %(modality_signals)s,
                        %(glossary_refs)s, %(acronym_refs)s, %(document_type)s,
                        %(page_start)s, %(page_end)s, %(primary_embedding)s
                    )
                """, {
                    "source_document": chunk["source_document"],
                    "classification": chunk.get("classification", "UNCLASSIFIED"),
                    "chunk_content": chunk["chunk_content"],
                    "paragraph_id": chunk["paragraph_id"],
                    "hierarchy_path": json.dumps(chunk["hierarchy_path"]),
                    "modality": chunk["modality"],
                    "modality_confidence": chunk.get("modality_confidence"),
                    "modality_signals": json.dumps(chunk.get("modality_signals", [])),
                    "glossary_refs": json.dumps(chunk.get("glossary_refs", [])),
                    "acronym_refs": json.dumps(chunk.get("acronym_refs", [])),
                    "document_type": chunk.get("document_type", ""),
                    "page_start": chunk.get("page_start"),
                    "page_end": chunk.get("page_end"),
                    "primary_embedding": str(chunk["primary_embedding"]),
                })
        conn.commit()
        return len(chunks)
    finally:
        conn.close()


def update_lifted_fields(record_id: str, fields: dict) -> None:
    """Update taxonomy fields and confidence scores for a lifted chunk."""
    safe = {}
    for k, v in fields.items():
        if isinstance(v, dict):
            safe[k] = json.dumps(v)
        elif isinstance(v, (list, tuple)):
            safe[k] = json.dumps(v)
        else:
            safe[k] = v
    safe["record_id"] = record_id

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE kd_doctrine SET
                    warfighting_function = %(warfighting_function)s,
                    warfighting_function_confidence = %(warfighting_function_confidence)s,
                    echelon = %(echelon)s,
                    echelon_confidence = %(echelon_confidence)s,
                    doctrinal_phase = %(doctrinal_phase)s,
                    doctrinal_phase_confidence = %(doctrinal_phase_confidence)s,
                    document_type_lifted = %(document_type_lifted)s,
                    document_type_lifted_confidence = %(document_type_lifted_confidence)s,
                    custom_metadata = %(custom_metadata)s::jsonb,
                    lift_model_version = %(lift_model_version)s,
                    lift_timestamp = now()
                WHERE record_id = %(record_id)s
            """, safe)
        conn.commit()
    finally:
        conn.close()


def get_unlifted_chunks(batch_size: int = 50, target_version: str = None) -> list[dict]:
    """Get chunks that need lifting."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if target_version:
                cur.execute("""
                    SELECT record_id, chunk_content, hierarchy_path, modality,
                           paragraph_id, source_document, modality_confidence
                    FROM kd_doctrine
                    WHERE lift_model_version IS NULL OR lift_model_version != %s
                    ORDER BY ingestion_timestamp ASC LIMIT %s
                """, (target_version, batch_size))
            else:
                cur.execute("""
                    SELECT record_id, chunk_content, hierarchy_path, modality,
                           paragraph_id, source_document, modality_confidence
                    FROM kd_doctrine
                    WHERE lift_model_version IS NULL
                    ORDER BY ingestion_timestamp ASC LIMIT %s
                """, (batch_size,))
            return cur.fetchall()
    finally:
        conn.close()


def get_chunk_count() -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) as cnt FROM kd_doctrine")
            return cur.fetchone()["cnt"]
    finally:
        conn.close()


def get_all_chunks() -> list[dict]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT record_id, chunk_content, paragraph_id, hierarchy_path,
                       modality, modality_confidence, modality_signals,
                       glossary_refs, acronym_refs, document_type,
                       page_start, page_end, source_document,
                       warfighting_function, warfighting_function_confidence,
                       echelon, echelon_confidence,
                       doctrinal_phase, doctrinal_phase_confidence
                FROM kd_doctrine ORDER BY paragraph_id
            """)
            return cur.fetchall()
    finally:
        conn.close()
