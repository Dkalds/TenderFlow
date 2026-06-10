"""FAISS index rebuild — checks staleness and enqueues rebuild if needed."""

from __future__ import annotations

from observability.logging import get_logger

log = get_logger(__name__)


def run() -> None:
    """Rebuild the FAISS index if data has changed since the last build.

    Checks whether the ``.cache_invalidation`` sentinel is more recent than
    the index file. If so, enqueues a full rebuild. No-op if FAISS is not
    available.
    """
    try:
        from services.faiss_index import _INDEX_PATH, _is_index_stale

        if not _INDEX_PATH.exists() or _is_index_stale(_INDEX_PATH):
            from scheduler.queue import enqueue_rebuild_embeddings

            enqueue_rebuild_embeddings()
            log.info("scheduler_faiss_rebuild_triggered")
        else:
            log.debug("scheduler_faiss_index_up_to_date")
    except Exception as exc:
        log.warning("scheduler_faiss_rebuild_failed", error=str(exc))
