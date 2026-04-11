"""Ingestion pipeline: PDF -> ADC chunks -> embed -> store in kd_doctrine.

Replicates the ADC pipeline from TorchAIKC/ADC (feature/moat-alignment).
The chunking logic is self-contained here so this prototype has no external
repo dependency.
"""
import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

ADC_REPO = Path(__file__).parent.parent.parent / "ADC"
if ADC_REPO.exists():
    sys.path.insert(0, str(ADC_REPO / "src"))


def run_adc_pipeline(pdf_path: Path, config_path: Path = None):
    """Run ADC chunking on a PDF. Returns list of ADCChunk objects."""
    from api import adc_chunk
    return adc_chunk(pdf_path, config_path=config_path)


def ingest(pdf_path: str, config_path: str = None, classification: str = "UNCLASSIFIED"):
    """Full ingestion: ADC chunk -> embed -> store in pgvector."""
    from src.embed import embed_texts
    from src.db import insert_chunks, get_chunk_count

    pdf = Path(pdf_path)
    cfg = Path(config_path) if config_path else None

    logger.info(f"Running ADC on {pdf.name}")
    adcs = run_adc_pipeline(pdf, cfg)
    logger.info(f"ADC produced {len(adcs)} chunks")

    texts = [adc.text for adc in adcs]
    logger.info(f"Computing embeddings for {len(texts)} chunks")
    embeddings = embed_texts(texts)

    rows = []
    for adc, emb in zip(adcs, embeddings):
        rows.append({
            "source_document": adc.publication,
            "classification": classification,
            "chunk_content": adc.text,
            "paragraph_id": adc.paragraph_id,
            "hierarchy_path": adc.hierarchy_path,
            "modality": adc.modality,
            "modality_confidence": adc.modality_confidence,
            "modality_signals": adc.modality_signals,
            "glossary_refs": adc.glossary_refs,
            "acronym_refs": adc.acronym_refs,
            "document_type": adc.document_type,
            "page_start": adc.page_start,
            "page_end": adc.page_end,
            "primary_embedding": emb,
        })

    logger.info(f"Inserting {len(rows)} rows into kd_doctrine")
    count = insert_chunks(rows)
    total = get_chunk_count()
    logger.info(f"Inserted {count} rows. Total in kd_doctrine: {total}")
    return count
