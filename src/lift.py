"""Semantic lifting: extract taxonomy fields from chunks via Claude structured output."""
import os
import json
import time
import logging
from dotenv import load_dotenv
import anthropic

from src.db import get_unlifted_chunks, update_lifted_fields

load_dotenv()
logger = logging.getLogger(__name__)

LIFT_VERSION = "claude-sonnet-doctrine-lift-v1"
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

EXTRACTION_PROMPT = """You are extracting structured military doctrine metadata from a text chunk.

Given the chunk text, its hierarchy path, and its modality classification, extract:

1. warfighting_function: One of "Movement and Maneuver", "Intelligence", "Fires", "Sustainment", "Mission Command", "Protection", or null if not applicable.
2. echelon: One of "Squad", "Platoon", "Company", "Battalion", "Brigade", "Division", "Corps", "Theater", or null if not specific to an echelon.
3. doctrinal_phase: One of "Phase 0 - Shape", "Phase I - Deter", "Phase II - Seize Initiative", "Phase III - Dominate", "Phase IV - Stabilize", "Phase V - Enable Civil Authority", or null if not phase-specific.
4. document_type: One of "ADP", "ADRP", "FM", "ATP", "TC", "TM", "JP", or null.

For each field, also provide a confidence score from 0.0 to 1.0.

Respond with valid JSON only. No explanation."""

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "warfighting_function": {"type": ["string", "null"]},
        "warfighting_function_confidence": {"type": "number"},
        "echelon": {"type": ["string", "null"]},
        "echelon_confidence": {"type": "number"},
        "doctrinal_phase": {"type": ["string", "null"]},
        "doctrinal_phase_confidence": {"type": "number"},
        "document_type": {"type": ["string", "null"]},
        "document_type_confidence": {"type": "number"},
    },
    "required": [
        "warfighting_function", "warfighting_function_confidence",
        "echelon", "echelon_confidence",
        "doctrinal_phase", "doctrinal_phase_confidence",
        "document_type", "document_type_confidence",
    ],
}


def lift_chunk(client: anthropic.Anthropic, chunk: dict) -> dict:
    """Extract taxonomy fields from a single chunk via Claude."""
    hierarchy = chunk.get("hierarchy_path", [])
    if isinstance(hierarchy, str):
        hierarchy = json.loads(hierarchy)

    user_content = (
        f"Hierarchy: {' > '.join(hierarchy)}\n"
        f"Modality: {chunk['modality']}\n"
        f"Paragraph: {chunk['paragraph_id']}\n"
        f"Source: {chunk['source_document']}\n\n"
        f"Text:\n{chunk['chunk_content']}"
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=EXTRACTION_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    parsed = json.loads(text)

    # Normalize: Claude sometimes returns {"value": "X", "confidence": Y}
    # instead of just "X" for taxonomy fields
    taxonomy_fields = [
        "warfighting_function", "echelon", "doctrinal_phase", "document_type"
    ]
    for field in taxonomy_fields:
        val = parsed.get(field)
        if isinstance(val, dict):
            parsed[field] = val.get("value")
            conf_key = f"{field}_confidence"
            if conf_key not in parsed or parsed[conf_key] == 0.0:
                parsed[conf_key] = val.get("confidence", 0.0)

    return parsed


def lift_batch(batch_size: int = 20, relift: bool = False):
    """Lift a batch of unlifted chunks."""
    target = LIFT_VERSION if relift else None
    chunks = get_unlifted_chunks(batch_size=batch_size, target_version=target or LIFT_VERSION)

    if not chunks:
        logger.info("No chunks need lifting")
        return 0

    logger.info(f"Lifting {len(chunks)} chunks with {MODEL}")
    client = anthropic.Anthropic()
    lifted = 0

    for i, chunk in enumerate(chunks):
        try:
            result = lift_chunk(client, chunk)
            fields = {
                "warfighting_function": result.get("warfighting_function"),
                "warfighting_function_confidence": result.get("warfighting_function_confidence", 0.0),
                "echelon": result.get("echelon"),
                "echelon_confidence": result.get("echelon_confidence", 0.0),
                "doctrinal_phase": result.get("doctrinal_phase"),
                "doctrinal_phase_confidence": result.get("doctrinal_phase_confidence", 0.0),
                "document_type_lifted": result.get("document_type"),
                "document_type_lifted_confidence": result.get("document_type_confidence", 0.0),
                "custom_metadata": "{}",
                "lift_model_version": LIFT_VERSION,
            }
            update_lifted_fields(str(chunk["record_id"]), fields)
            lifted += 1

            if (i + 1) % 10 == 0:
                logger.info(f"  Lifted {i + 1}/{len(chunks)}")

        except anthropic.RateLimitError:
            wait = min(60, 2 ** (i % 5))
            logger.warning(f"Rate limited, waiting {wait}s")
            time.sleep(wait)
            continue
        except Exception as e:
            logger.error(f"Failed to lift {chunk['paragraph_id']}: {e}")
            continue

    logger.info(f"Lifted {lifted}/{len(chunks)} chunks")
    return lifted
