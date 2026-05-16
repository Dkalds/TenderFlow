"""Cola de tareas asíncronas opcional — usa Dramatiq si está disponible.

Si ``DRAMATIQ_BROKER_URL`` está en settings (ej. ``redis://localhost:6379/0``),
crea actores Dramatiq sobre Redis. En caso contrario usa un StubBroker
(ejecución síncrona inline — apto para dev y tests).

Actores disponibles:
- ``enqueue_bulk_download(year, month)`` — delega en scraper.bulk_downloader
- ``enqueue_rebuild_embeddings()``       — delega en dashboard.faiss_index.build

Uso:
    from scheduler.queue import enqueue_bulk_download
    enqueue_bulk_download.send(2024, 3)   # async si broker configurado
"""

from __future__ import annotations

from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

# ── Broker setup ──────────────────────────────────────────────────────────────


def _setup_broker() -> Any:
    try:
        import dramatiq  # type: ignore[import]

        from config import settings

        broker_url = getattr(settings, "DRAMATIQ_BROKER_URL", "")
        if broker_url:
            try:
                from dramatiq.brokers.redis import RedisBroker  # type: ignore[import]

                broker = RedisBroker(url=broker_url)
                dramatiq.set_broker(broker)
                log.info("dramatiq.broker_set", url=broker_url.split("@")[-1])
            except Exception as exc:
                log.warning("dramatiq.redis_broker_failed", error=str(exc), fallback="stub")
                from dramatiq.brokers.stub import StubBroker  # type: ignore[import]

                broker = StubBroker()
                dramatiq.set_broker(broker)
        else:
            from dramatiq.brokers.stub import StubBroker  # type: ignore[import]

            broker = StubBroker()
            dramatiq.set_broker(broker)
            log.info("dramatiq.stub_broker_active")
        return dramatiq
    except ImportError:
        return None


_dramatiq = _setup_broker()

# ── Actor definitions ─────────────────────────────────────────────────────────

if _dramatiq is not None:

    @_dramatiq.actor(max_retries=2, time_limit=3600_000)  # 1 h max
    def enqueue_bulk_download(year: int, month: int) -> None:
        """Descarga el bulk XML de un mes completo en background."""
        from scraper.bulk_downloader import download_month

        log.info("queue.bulk_download.start", year=year, month=month)
        result = download_month(year, month, force=False)
        log.info("queue.bulk_download.done", path=str(result))

    @_dramatiq.actor(max_retries=1, time_limit=7200_000)  # 2 h max
    def enqueue_rebuild_embeddings() -> None:
        """Reconstruye el índice FAISS de embeddings en background."""
        import pandas as pd

        from dashboard.faiss_index import FaissIndex
        from db.database import connect

        log.info("queue.rebuild_embeddings.start")
        with connect() as c:
            cur = c.execute("SELECT id_externo, titulo, descripcion FROM licitaciones")
            cols = [d[0] for d in cur.description]
            df = pd.DataFrame(cur.fetchall(), columns=cols)
        idx = FaissIndex.build(df)
        idx.save()
        log.info("queue.rebuild_embeddings.done", n=len(df))

else:
    # Fallback stub functions for environments without dramatiq

    def enqueue_bulk_download(year: int, month: int) -> None:  # type: ignore[misc]
        """Inline fallback (dramatiq not installed)."""
        from scraper.bulk_downloader import download_month

        download_month(year, month, force=False)

    def enqueue_rebuild_embeddings() -> None:  # type: ignore[misc]
        """Inline fallback (dramatiq not installed)."""
        import pandas as pd

        from dashboard.faiss_index import FaissIndex
        from db.database import connect

        with connect() as c:
            cur = c.execute("SELECT id_externo, titulo, descripcion FROM licitaciones")
            cols = [d[0] for d in cur.description]
            df = pd.DataFrame(cur.fetchall(), columns=cols)
        idx = FaissIndex.build(df)
        idx.save()
