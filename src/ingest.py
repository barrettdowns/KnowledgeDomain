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


def ingest_directory(blob_uri: str, config_path: str = None, progress_cb=None):
    """Run the moat SkillSet (ADC + embed_text) over a directory of PDFs.

    Mirror of ingest_naive.ingest_naive_corpus() but using the existing ADC
    pipeline. Used by src.prefect_dispatch.run_ingest() in LOCAL mode for
    kb-doctrine-moat.
    """
    if blob_uri.startswith("file://"):
        root = Path(blob_uri[len("file://") :])
    else:
        root = Path(blob_uri)

    if not root.exists():
        raise FileNotFoundError(f"Moat corpus root not found: {root}")

    pdfs = sorted(root.glob("*.pdf"))
    if progress_cb:
        progress_cb(f"Found {len(pdfs)} PDFs under {root}")

    stats = {"per_pdf": {}, "total_chunks": 0, "pdf_count": len(pdfs)}
    for pdf in pdfs:
        if progress_cb:
            progress_cb(f"Running ADC + embed on {pdf.name}")
        n = ingest(str(pdf), config_path=config_path)
        stats["per_pdf"][pdf.name] = n
        stats["total_chunks"] += n
    if progress_cb:
        progress_cb(f"Moat SkillSet done: {stats['total_chunks']} chunks across {stats['pdf_count']} PDFs")
    return stats
