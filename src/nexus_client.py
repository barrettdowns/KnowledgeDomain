"""Nexus HTTP client with two-mode (LIVE / LOCAL) operation.

When NEXUS_API_URL is set and the /help/ endpoint responds, this module
makes real HTTP calls to the Nexus FastAPI service per RFC-0001. Otherwise
it falls back to in-process equivalents that read directly from local
Postgres projection tables.

All retrieval calls normalize to a common hit shape matching RFC-0001
§1.6.3's "standard hit format" so consumers (Streamlit pages, benchmarks)
do not need per-mode parsers.

Routes targeted (primary, RFC-0001):
- POST /kd/knowledge-bases/{kb_id}/query
- POST /kd/knowledge-bases/{kb_id}/runs
- GET  /kd/knowledge-bases/{kb_id}/runs/{run_id}
- POST /kd/knowledge-domains/{kd_id}/agent/messages
- POST /kd/knowledge-domains/from-yaml
- POST /complete (legacy completion proxy, predates RFC-0001)

Legacy fallback (kept for environments where /kd/... is not implemented):
- POST /a2a/search-agent
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

NEXUS_API_URL = os.getenv("NEXUS_API_URL", "").rstrip("/")
NEXUS_KD_ID = os.getenv("NEXUS_KD_ID", "kd-doctrine")
NEXUS_KB_ID_DOCTRINE_NAIVE = os.getenv("NEXUS_KB_ID_DOCTRINE_NAIVE", "kb-doctrine-naive")
NEXUS_KB_ID_DOCTRINE_MOAT = os.getenv("NEXUS_KB_ID_DOCTRINE_MOAT", "kb-doctrine-moat")

# Default HTTP timeout. Override per-call if a route is known to be slow.
DEFAULT_TIMEOUT_S = 30.0

# Module-level cache of the LIVE probe. Cleared by reset_live_cache().
_live_probe_cache: bool | None = None


def reset_live_cache() -> None:
    """Force the next is_live() call to re-probe."""
    global _live_probe_cache
    _live_probe_cache = None


def is_live() -> bool:
    """True iff NEXUS_API_URL is set and GET /help/ responds 200.

    Cached per-process to avoid hammering the network on every Streamlit rerun.
    Call reset_live_cache() to force a re-probe.
    """
    global _live_probe_cache
    if _live_probe_cache is not None:
        return _live_probe_cache
    if not NEXUS_API_URL:
        _live_probe_cache = False
        return False
    try:
        r = httpx.get(f"{NEXUS_API_URL}/help/", timeout=3.0)
        _live_probe_cache = r.status_code == 200
    except Exception as e:  # network down, dns, refused, etc.
        logger.info("Nexus probe failed (%s); defaulting to LOCAL mode", e)
        _live_probe_cache = False
    return _live_probe_cache


def mode_label() -> str:
    """Human-readable mode label for the sidebar."""
    return "LIVE (Nexus reachable)" if is_live() else "LOCAL (Nexus not configured)"


# ---------------------------------------------------------------------------
# Hit shape normalization (RFC-0001 §1.6.3 standard hit format)
# ---------------------------------------------------------------------------

def normalize_hit(raw: dict[str, Any], projection_default: str = "text_chunks") -> dict[str, Any]:
    """Coerce a raw hit (from any retrieval path) into the standard shape.

    Standard keys: chunk_id, score, content, metadata, projection, siblings.
    Optional keys passed through: hierarchy_path, modality, paragraph_id,
    warfighting_function, modality_confidence, etc. — anything moat-specific
    lands in `metadata` and at the top level for backward compat with existing
    Streamlit page code.
    """
    chunk_id = (
        raw.get("chunk_id")
        or raw.get("paragraph_id")
        or raw.get("record_id")
        or raw.get("id")
        or ""
    )
    return {
        "chunk_id": str(chunk_id),
        "score": float(raw.get("score") or 0.0),
        "content": raw.get("content") or raw.get("chunk_content") or "",
        "projection": raw.get("projection") or projection_default,
        "metadata": raw.get("metadata") or {
            k: raw.get(k)
            for k in (
                "paragraph_id",
                "hierarchy_path",
                "modality",
                "modality_confidence",
                "warfighting_function",
                "warfighting_function_confidence",
                "echelon",
                "section_id",
                "source_document",
                "source_uri",
                "page_start",
            )
            if raw.get(k) is not None
        },
        "siblings": raw.get("siblings") or [],
        # Pass-through for legacy ui.py code paths:
        **{k: v for k, v in raw.items() if k not in {"chunk_id", "score", "content", "projection", "metadata", "siblings"}},
    }


# ---------------------------------------------------------------------------
# Knowledge Base query  (RFC-0001 §1.6.5.6.1)
# ---------------------------------------------------------------------------

def kb_query(
    kb_id: str,
    query: str,
    top_k: int = 10,
    filters: dict[str, Any] | None = None,
    projection_kinds: list[str] | None = None,
    include_siblings: bool = False,
    min_confidence: float = 0.0,
) -> list[dict[str, Any]]:
    """POST /kd/knowledge-bases/{kb_id}/query in LIVE mode; local fallback otherwise.

    Returns a list of normalized hits matching RFC-0001 §1.6.3's standard hit format.
    """
    if projection_kinds is None:
        projection_kinds = ["text"]

    if is_live():
        body = {
            "query": query,
            "top_k": top_k,
            "projection_kinds": projection_kinds,
            "include_siblings": include_siblings,
        }
        if filters:
            body["filters"] = filters
        try:
            r = httpx.post(
                f"{NEXUS_API_URL}/kd/knowledge-bases/{kb_id}/query",
                json=body,
                timeout=DEFAULT_TIMEOUT_S,
            )
            if r.status_code == 200:
                data = r.json()
                hits = data.get("hits") or data.get("results") or data.get("result", {}).get("hits") or []
                return [normalize_hit(h) for h in hits]
            logger.warning("LIVE kb_query %s returned HTTP %d; falling back to LOCAL", kb_id, r.status_code)
        except Exception as e:
            logger.warning("LIVE kb_query %s errored (%s); falling back to LOCAL", kb_id, e)

    return _kb_query_local(kb_id, query, top_k, filters, projection_kinds, include_siblings, min_confidence)


def _kb_query_local(
    kb_id: str,
    query: str,
    top_k: int,
    filters: dict[str, Any] | None,
    projection_kinds: list[str],
    include_siblings: bool,
    min_confidence: float,
) -> list[dict[str, Any]]:
    """LOCAL fallback: route by kb_id to the right projection retriever."""
    if kb_id == NEXUS_KB_ID_DOCTRINE_NAIVE:
        from src.retrieve_naive import query_naive_hybrid

        raws = query_naive_hybrid(query, top_k=top_k)
        return [normalize_hit(r, projection_default="text_chunks") for r in raws]

    if kb_id == NEXUS_KB_ID_DOCTRINE_MOAT:
        from src.retrieve import retrieve

        raws = retrieve(query, top_k=top_k, filters=filters or None, min_confidence=min_confidence)
        return [normalize_hit(r, projection_default="text_chunks") for r in raws]

    logger.warning("kb_query: unknown kb_id %r in LOCAL mode; returning empty", kb_id)
    return []


# ---------------------------------------------------------------------------
# Knowledge Domain chat  (RFC-0001 §1.6.5.8)
# ---------------------------------------------------------------------------

def kd_chat(
    message: str,
    kd_id: str | None = None,
    conversation_id: str | None = None,
    top_k_per_base: int = 5,
) -> dict[str, Any]:
    """POST /kd/knowledge-domains/{kd_id}/agent/messages in LIVE mode.

    LOCAL fallback: per-base retrieve over both naive and moat KBs, merge,
    naive concatenation (no LLM rerank). Returns:
        {"assistant_message": str, "citations": [...], "retrieved_chunks": [...]}
    """
    kd_id = kd_id or NEXUS_KD_ID
    if is_live():
        try:
            r = httpx.post(
                f"{NEXUS_API_URL}/kd/knowledge-domains/{kd_id}/agent/messages",
                json={"message": message, "conversation_id": conversation_id},
                timeout=60.0,
            )
            if r.status_code == 200:
                return r.json()
            logger.warning("LIVE kd_chat returned HTTP %d; falling back to LOCAL", r.status_code)
        except Exception as e:
            logger.warning("LIVE kd_chat errored (%s); falling back to LOCAL", e)

    # LOCAL: per-base retrieve → merge → return retrieval bundle (no LLM call).
    naive_hits = kb_query(NEXUS_KB_ID_DOCTRINE_NAIVE, message, top_k=top_k_per_base)
    moat_hits = kb_query(NEXUS_KB_ID_DOCTRINE_MOAT, message, top_k=top_k_per_base)
    merged = sorted(naive_hits + moat_hits, key=lambda h: h["score"], reverse=True)[: top_k_per_base * 2]
    return {
        "assistant_message": None,
        "retrieved_chunks": merged,
        "citations": [{"chunk_id": h["chunk_id"], "score": h["score"]} for h in merged],
        "mode": "LOCAL-no-llm",
    }


# ---------------------------------------------------------------------------
# Indexer runs  (RFC-0001 §1.6.5.6.2)
# ---------------------------------------------------------------------------

def dispatch_kb_run(
    kb_id: str,
    blob_uri: str,
    credential_ref: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST /kd/knowledge-bases/{kb_id}/runs in LIVE mode.

    Returns the IndexerRun resource (id, external_run_id, status, ...).
    Raises RuntimeError if not in LIVE mode — local in-process equivalents
    live in src/prefect_dispatch.py to keep the LOCAL/LIVE separation clean.
    """
    if not is_live():
        raise RuntimeError(
            "dispatch_kb_run requires LIVE mode (NEXUS_API_URL set + /help/ reachable). "
            "For LOCAL mode use src.prefect_dispatch.run_ingest / run_lift instead."
        )

    body: dict[str, Any] = {"blob_uri": blob_uri}
    if credential_ref is not None:
        body["credential_ref"] = credential_ref
    if parameters is not None:
        body["parameters"] = parameters

    r = httpx.post(
        f"{NEXUS_API_URL}/kd/knowledge-bases/{kb_id}/runs",
        json=body,
        timeout=DEFAULT_TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json()


def poll_kb_run(kb_id: str, run_id: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """GET /kd/knowledge-bases/{kb_id}/runs/{run_id} in LIVE mode."""
    if not is_live():
        raise RuntimeError("poll_kb_run requires LIVE mode")
    r = httpx.get(
        f"{NEXUS_API_URL}/kd/knowledge-bases/{kb_id}/runs/{run_id}",
        timeout=timeout_s,
    )
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Knowledge Domain bundle import  (RFC-0001 §1.6.5.10)
# ---------------------------------------------------------------------------

def import_kd_bundle(yaml_text: str) -> dict[str, Any]:
    """POST /kd/knowledge-domains/from-yaml in LIVE mode."""
    if not is_live():
        raise RuntimeError("import_kd_bundle requires LIVE mode")
    r = httpx.post(
        f"{NEXUS_API_URL}/kd/knowledge-domains/from-yaml",
        content=yaml_text,
        headers={"Content-Type": "text/yaml"},
        timeout=60.0,
    )
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Completion proxy  (legacy Nexus surface, used by Phase 8 for CODEX + lifting)
# ---------------------------------------------------------------------------

def complete(messages: list[dict[str, str]], model: str | None = None, **kwargs) -> dict[str, Any]:
    """POST /complete in LIVE mode; falls back to direct Anthropic SDK in LOCAL.

    Returns a dict with at least {"content": str, "model": str}. In LIVE mode
    the Nexus completion proxy normalizes choices; in LOCAL mode we wrap
    anthropic.Anthropic().messages.create() to the same shape.
    """
    if is_live():
        body: dict[str, Any] = {"messages": messages}
        if model is not None:
            body["model"] = model
        body.update(kwargs)
        try:
            r = httpx.post(
                f"{NEXUS_API_URL}/complete",
                json=body,
                timeout=60.0,
            )
            if r.status_code == 200:
                data = r.json()
                choices = data.get("choices") or []
                content = ""
                if choices:
                    content = choices[0].get("message", {}).get("content", "") or choices[0].get("text", "")
                return {"content": content, "model": data.get("model", model or ""), "raw": data}
            logger.warning("LIVE complete returned HTTP %d; falling back to Anthropic SDK", r.status_code)
        except Exception as e:
            logger.warning("LIVE complete errored (%s); falling back to Anthropic SDK", e)

    return _complete_local(messages, model=model, **kwargs)


def _complete_local(messages: list[dict[str, str]], model: str | None = None, **kwargs) -> dict[str, Any]:
    """LOCAL fallback: anthropic.Anthropic().messages.create()."""
    import anthropic

    mdl = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    system = None
    user_messages: list[dict[str, str]] = []
    for m in messages:
        if m.get("role") == "system":
            system = m.get("content", "")
        else:
            user_messages.append({"role": m["role"], "content": m["content"]})

    client = anthropic.Anthropic()
    create_kwargs: dict[str, Any] = {
        "model": mdl,
        "max_tokens": kwargs.get("max_tokens", 1024),
        "messages": user_messages,
    }
    if system:
        create_kwargs["system"] = system
    if "temperature" in kwargs:
        create_kwargs["temperature"] = kwargs["temperature"]

    resp = client.messages.create(**create_kwargs)
    text = resp.content[0].text if resp.content else ""
    return {"content": text, "model": mdl, "raw": resp}


# ---------------------------------------------------------------------------
# Legacy fallback  (deprecated; only used if /kd/... routes are not implemented)
# ---------------------------------------------------------------------------

def search_agent_legacy(query: str, top_k: int = 10) -> list[dict[str, Any]]:
    """DEPRECATED. POST /a2a/search-agent. Use kb_query() instead.

    Kept as a final fallback for environments where /kd/knowledge-bases/{kb_id}/query
    is not yet implemented on the running Nexus. Phase 1's route-availability matrix
    determines whether kb_query() works against LIVE Nexus; if not, callers may
    explicitly route to this legacy endpoint instead.
    """
    if not is_live():
        raise RuntimeError("search_agent_legacy requires LIVE mode")
    r = httpx.post(
        f"{NEXUS_API_URL}/a2a/search-agent",
        json={"query": query, "top_k": top_k},
        timeout=DEFAULT_TIMEOUT_S,
    )
    r.raise_for_status()
    data = r.json()
    docs = data.get("evidence") or data.get("documents") or data.get("result", {}).get("evidence") or []
    return [normalize_hit(d) for d in docs]
