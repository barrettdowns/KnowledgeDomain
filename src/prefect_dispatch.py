"""Prefect dispatch with LOCAL fallback.

In LIVE mode, the Streamlit "Run ingestion" / "Run lifting" buttons dispatch
to RFC-0001's POST /kd/knowledge-bases/{kb_id}/runs endpoint and Nexus
resolves the indexer flow from the KB record's indexer_id (one indexer per
base; reuse is via skill_set_id on the indexer).

In LOCAL mode, the same buttons run the equivalent pipeline in-process so
the demo never blocks on an external Prefect server. Run state is tracked
in a module-level dict (per-Streamlit-process; resets on restart).
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable

from src import nexus_client

logger = logging.getLogger(__name__)

# Module-level in-memory run registry for LOCAL mode.
# Schema mirrors RFC-0001 IndexerRun where possible.
_LOCAL_RUNS: dict[str, dict[str, Any]] = {}


def list_recent_runs(kb_id: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    """Return recent runs across LOCAL and (where polled) LIVE.

    LOCAL runs are returned from the in-memory registry. LIVE runs are
    returned only if we have cached entries — the LIVE path uses
    nexus_client.poll_kb_run() on demand rather than maintaining a list endpoint
    client-side (the RFC currently scopes runs under kb_id without a list route).
    """
    runs = list(_LOCAL_RUNS.values())
    if kb_id:
        runs = [r for r in runs if r.get("kb_id") == kb_id]
    runs.sort(key=lambda r: r.get("created_at", 0), reverse=True)
    return runs[:limit]


def run_ingest(
    kb_id: str,
    blob_uri: str,
    *,
    parameters: dict[str, Any] | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Dispatch indexer ingestion for a KB.

    LIVE: POST /kd/knowledge-bases/{kb_id}/runs with IndexerRunCreate body.
    LOCAL: routes by kb_id to the right in-process ingester.
    Returns an IndexerRun-shaped dict with id, status, external_run_id (LIVE only).
    """
    if nexus_client.is_live():
        try:
            run = nexus_client.dispatch_kb_run(
                kb_id=kb_id, blob_uri=blob_uri, parameters=parameters
            )
            _LOCAL_RUNS[run.get("id", str(uuid.uuid4()))] = {**run, "kb_id": kb_id, "mode": "LIVE"}
            return run
        except Exception as e:
            logger.warning("LIVE dispatch_kb_run failed (%s); falling back to LOCAL in-process", e)

    return _run_ingest_local(kb_id, blob_uri, parameters=parameters, progress_cb=progress_cb)


def _run_ingest_local(
    kb_id: str,
    blob_uri: str,
    *,
    parameters: dict[str, Any] | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """LOCAL: in-process ingestion to the right projection table."""
    run_id = str(uuid.uuid4())
    record: dict[str, Any] = {
        "id": run_id,
        "kb_id": kb_id,
        "indexer_id": _kb_to_indexer(kb_id),
        "blob_uri": blob_uri,
        "parameters": parameters or {},
        "external_run_id": None,
        "status": "running",
        "mode": "LOCAL",
        "created_at": time.time(),
        "started_at": time.time(),
        "completed_at": None,
        "error_message": None,
        "stats": {},
    }
    _LOCAL_RUNS[run_id] = record

    def _emit(msg: str) -> None:
        if progress_cb:
            progress_cb(msg)
        logger.info("[%s] %s", kb_id, msg)

    try:
        if kb_id == nexus_client.NEXUS_KB_ID_DOCTRINE_NAIVE:
            _emit("Running naive SkillSet (split_pdf + embed_text) on doctrine corpus")
            from src.ingest_naive import ingest_naive_corpus

            stats = ingest_naive_corpus(blob_uri, progress_cb=_emit)
        elif kb_id == nexus_client.NEXUS_KB_ID_DOCTRINE_MOAT:
            _emit("Running moat SkillSet (ADC + embed_text) on doctrine corpus")
            from src.ingest import ingest_directory  # existing ADC pipeline

            stats = ingest_directory(blob_uri, progress_cb=_emit)
        else:
            raise ValueError(f"Unknown kb_id: {kb_id!r}")

        record["status"] = "succeeded"
        record["stats"] = stats or {}
    except Exception as e:
        record["status"] = "failed"
        record["error_message"] = str(e)
        logger.exception("LOCAL ingest for %s failed", kb_id)
    finally:
        record["completed_at"] = time.time()

    return record


def run_lift(
    kb_id: str,
    *,
    batch_size: int = 20,
    relift: bool = False,
    progress_cb: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Dispatch lifting for the moat KB.

    LIVE: POST /kd/knowledge-bases/{kb_id}/runs with parameters carrying the
    lifting-only mode flag. (In RFC-0001's SkillSet model, lifting is part of
    the indexer flow; a separate "lift only" run uses parameters to skip the
    chunking skill.) LOCAL: calls src.lift.lift_batch() in-process.
    """
    if kb_id != nexus_client.NEXUS_KB_ID_DOCTRINE_MOAT:
        raise ValueError(f"Lifting is only defined for the moat KB; got kb_id={kb_id!r}")

    if nexus_client.is_live():
        try:
            params = {"mode": "lift_only", "batch_size": batch_size, "relift": relift}
            run = nexus_client.dispatch_kb_run(
                kb_id=kb_id,
                blob_uri="lift://moat",  # sentinel: no blob, lift existing chunks
                parameters=params,
            )
            _LOCAL_RUNS[run.get("id", str(uuid.uuid4()))] = {**run, "kb_id": kb_id, "mode": "LIVE"}
            return run
        except Exception as e:
            logger.warning("LIVE lift dispatch failed (%s); falling back to LOCAL", e)

    return _run_lift_local(kb_id, batch_size=batch_size, relift=relift, progress_cb=progress_cb)


def _run_lift_local(
    kb_id: str,
    *,
    batch_size: int,
    relift: bool,
    progress_cb: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """LOCAL: src.lift.lift_batch() in-process."""
    run_id = str(uuid.uuid4())
    record: dict[str, Any] = {
        "id": run_id,
        "kb_id": kb_id,
        "indexer_id": _kb_to_indexer(kb_id),
        "blob_uri": "lift://moat",
        "parameters": {"mode": "lift_only", "batch_size": batch_size, "relift": relift},
        "external_run_id": None,
        "status": "running",
        "mode": "LOCAL",
        "created_at": time.time(),
        "started_at": time.time(),
        "completed_at": None,
        "error_message": None,
        "stats": {},
    }
    _LOCAL_RUNS[run_id] = record

    def _emit(msg: str) -> None:
        if progress_cb:
            progress_cb(msg)
        logger.info("[%s lift] %s", kb_id, msg)

    try:
        from src.lift import lift_batch

        _emit(f"Lifting batch_size={batch_size} relift={relift}")
        lifted = lift_batch(batch_size=batch_size, relift=relift)
        record["status"] = "succeeded"
        record["stats"] = {"lifted": lifted}
    except Exception as e:
        record["status"] = "failed"
        record["error_message"] = str(e)
        logger.exception("LOCAL lift for %s failed", kb_id)
    finally:
        record["completed_at"] = time.time()

    return record


def _kb_to_indexer(kb_id: str) -> str:
    """LOCAL convenience: map KB id to its catalog-fixture indexer_id.

    In LIVE mode the substrate resolves indexer_id from the KB record. The
    LOCAL mapping just mirrors the catalog YAML fixtures from Phase 3 so the
    run record we surface in the UI carries the right indexer label.
    """
    if kb_id == nexus_client.NEXUS_KB_ID_DOCTRINE_NAIVE:
        return "idxr-doctrine-naive"
    if kb_id == nexus_client.NEXUS_KB_ID_DOCTRINE_MOAT:
        return "idxr-doctrine-enriched"
    return "idxr-unknown"
