"""Compile ADC chunks into CODEX objects via Claude.

Groups chunks by chapter/section, routes by modality, uses Claude to extract
triggers, causal chains, allowed actions, and constraints. Uses the 4 sample
CODEX objects from the CODEX repo as few-shot examples.
"""
import os
import json
import time
import logging
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv
import anthropic

from src.db import get_all_chunks

load_dotenv()
logger = logging.getLogger(__name__)

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
SAMPLE_OBJECTS_PATH = Path(__file__).parent.parent / "codex" / "data" / "sample_codex_objects.json"
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "compiled_codex_objects.json"

COMPILATION_PROMPT = """You are compiling structured CODEX objects from military doctrine chunks.

A CODEX object represents a compiled tactical pattern that a rule engine can evaluate decision artifacts against. Each object must include:

- codex_id: unique identifier (format: CODEX-YYYY-NNNN)
- context_envelope: object with echelon, phase, mission_type, domain
- triggers: conditions that activate this doctrine
- required_observations: what must be confirmed before applying
- allowed_actions: list of objects with action, parameters, intended_effects
- constraints: boundaries on action
- tradeoffs: list of objects with action, degradation, compensation
- causal_chains: list of objects with chain_id, pattern_name, links (each link has condition, effect, mechanism, exception), provenance
- measures: how to assess effectiveness
- provenance: doctrinal citations

Here is an example of a well-formed CODEX object:
{example}

Now compile a CODEX object from these doctrine chunks about "{topic}". Use the modality classifications to guide what becomes an allowed_action (REQUIREMENT/PERMISSION chunks), constraint (PROHIBITION chunks), or contextual information (DESCRIPTIVE/DEFINITION chunks).

Respond with a single valid JSON object. No explanation."""


def group_chunks_by_section(chunks: list[dict]) -> dict[str, list[dict]]:
    """Group chunks by their top-level section heading."""
    groups = defaultdict(list)
    for chunk in chunks:
        hierarchy = chunk.get("hierarchy_path", [])
        if isinstance(hierarchy, str):
            hierarchy = json.loads(hierarchy)
        if len(hierarchy) >= 2:
            key = f"{hierarchy[0]} > {hierarchy[1]}"
        elif len(hierarchy) == 1:
            key = hierarchy[0]
        else:
            key = "Ungrouped"
        groups[key].append(chunk)
    return dict(groups)


def format_chunks_for_prompt(chunks: list[dict]) -> str:
    """Format a group of chunks for the compilation prompt."""
    lines = []
    for c in chunks:
        modality = c.get("modality", "DESCRIPTIVE")
        pid = c.get("paragraph_id", "?")
        text = c.get("chunk_content", "")[:500]
        wf = c.get("warfighting_function", "")
        echelon = c.get("echelon", "")
        lines.append(f"[{pid}] [{modality}] [WF:{wf}] [Echelon:{echelon}]\n{text}\n")
    return "\n---\n".join(lines)


def compile_codex_objects(max_sections: int = 8):
    """Compile CODEX objects from the doctrine KD."""
    chunks = get_all_chunks()
    if not chunks:
        logger.warning("No chunks in database")
        return []

    example_obj = json.load(open(SAMPLE_OBJECTS_PATH))[0]
    example_json = json.dumps(example_obj, indent=2)

    groups = group_chunks_by_section(chunks)
    logger.info(f"Found {len(groups)} section groups from {len(chunks)} chunks")

    # Select sections with enough substance (5+ chunks, mix of modalities)
    candidate_sections = []
    for section, section_chunks in groups.items():
        if len(section_chunks) >= 4:
            modalities = set(c.get("modality") for c in section_chunks)
            if len(modalities) >= 2:
                candidate_sections.append((section, section_chunks))

    candidate_sections.sort(key=lambda x: len(x[1]), reverse=True)
    selected = candidate_sections[:max_sections]
    logger.info(f"Selected {len(selected)} sections for compilation")

    client = anthropic.Anthropic()
    compiled = []
    counter = 1

    for section_name, section_chunks in selected:
        chunks_text = format_chunks_for_prompt(section_chunks)
        prompt = COMPILATION_PROMPT.format(
            example=example_json,
            topic=section_name,
        )

        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=prompt,
                messages=[{"role": "user", "content": chunks_text}],
            )
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            obj = json.loads(text)
            obj["codex_id"] = f"CODEX-ADP30-{counter:04d}"
            obj["provenance"] = [
                f"ADP 3-0 {c['paragraph_id']}" for c in section_chunks[:5]
            ]
            compiled.append(obj)
            counter += 1

            ce = obj.get("context_envelope", {})
            logger.info(
                f"  Compiled: {obj['codex_id']} from '{section_name}' "
                f"({len(section_chunks)} chunks) -> "
                f"{ce.get('mission_type', '?')} at {ce.get('echelon', '?')}"
            )

        except anthropic.RateLimitError:
            logger.warning("Rate limited, waiting 30s")
            time.sleep(30)
            continue
        except Exception as e:
            logger.error(f"Failed to compile '{section_name}': {e}")
            continue

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(compiled, f, indent=2)
    logger.info(f"Wrote {len(compiled)} CODEX objects to {OUTPUT_PATH}")
    return compiled
