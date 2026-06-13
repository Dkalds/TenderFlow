"""Cola de tareas asíncronas opcional — usa Dramatiq si está disponible.

Si ``DRAMATIQ_BROKER_URL`` está en settings (ej. ``redis://localhost:6379/0``),
crea actores Dramatiq sobre Redis. En caso contrario usa un StubBroker
(ejecución síncrona inline — apto para dev y tests).

Actores disponibles:
- ``enqueue_bulk_download(year, month)`` — delega en scraper.bulk_downloader
- ``enqueue_rebuild_embeddings()``       — delega en dashboard.faiss_index.build

Cuando un actor agota sus reintentos Dramatiq, ``DLQMiddleware`` registra el
fallo en ``failed_extractions`` (DLQ SQLite) y lanza una alerta.

Uso:
    from scheduler.queue import enqueue_bulk_download
    enqueue_bulk_download.send(2024, 3)   # async si broker configurado
"""

from __future__ import annotations

from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

# ── DLQ Middleware ────────────────────────────────────────────────────────────


def _make_dlq_middleware() -> Any | None:
    """Crea el DLQMiddleware de Dramatiq que registra fallos en la DLQ SQLite.

    Devuelve None si Dramatiq no está disponible.
    """
    try:
        import dramatiq  # type: ignore[import-not-found]

        class DLQMiddleware(dramatiq.Middleware):  # type: ignore[misc]
            """Registra mensajes fallidos en la DLQ SQLite tras agotar retries Dramatiq."""

            def after_process_message(
                self,
                broker: Any,
                message: Any,
                *,
                result: Any = None,
                exception: BaseException | None = None,
            ) -> None:
                # Solo actuar si hubo excepción y no quedan más reintentos
                if exception is None:
                    return
                retries = message.options.get("retries", 0)
                max_retries = message.options.get("max_retries", 0)
                if retries < max_retries:
                    return  # Dramatiq reintentará por sí mismo
                # Agotados los reintentos de Dramatiq → registrar en DLQ SQLite
                try:
                    from db.dlq import record_failure

                    record_failure(
                        None,
                        message.actor_name,
                        exception,
                        payload_ref=str(message.message_id),
                    )
                    log.warning(
                        "dramatiq_dlq_recorded",
                        actor=message.actor_name,
                        message_id=str(message.message_id),
                        error=str(exception),
                    )
                except Exception as dlq_exc:
                    log.warning("dramatiq_dlq_record_failed", error=str(dlq_exc))

        return DLQMiddleware()
    except ImportError:
        return None


# ── Broker setup ──────────────────────────────────────────────────────────────


def _setup_broker() -> Any:
    try:
        import dramatiq

        from config import settings

        queue_mode = getattr(settings, "QUEUE_MODE", "auto")
        dlq_middleware = _make_dlq_middleware()

        # Fail-fast: if QUEUE_MODE=dramatiq but no broker URL, crash early
        broker_url = getattr(settings, "DRAMATIQ_BROKER_URL", "")
        if queue_mode == "dramatiq" and not broker_url:
            raise RuntimeError(
                "QUEUE_MODE=dramatiq but DRAMATIQ_BROKER_URL is empty. "
                "Set DRAMATIQ_BROKER_URL or use QUEUE_MODE=auto for fallback."
            )

        if queue_mode == "inline":
            # Force inline mode regardless of dramatiq availability
            log.info("queue.inline_mode_forced")
            return None

        if broker_url:
            try:
                from dramatiq.brokers.redis import RedisBroker  # type: ignore[import-not-found]

                broker = RedisBroker(url=broker_url)
                if dlq_middleware:
                    broker.add_middleware(dlq_middleware)
                dramatiq.set_broker(broker)
                log.info("dramatiq.broker_set", url=broker_url.split("@")[-1])
            except Exception as exc:
                if queue_mode == "dramatiq":
                    raise RuntimeError(
                        f"QUEUE_MODE=dramatiq but Redis connection failed: {exc}"
                    ) from exc
                log.warning("dramatiq.redis_broker_failed", error=str(exc), fallback="stub")
                from dramatiq.brokers.stub import StubBroker  # type: ignore[import-not-found]

                broker = StubBroker()
                if dlq_middleware:
                    broker.add_middleware(dlq_middleware)
                dramatiq.set_broker(broker)
        else:
            from dramatiq.brokers.stub import StubBroker

            broker = StubBroker()
            if dlq_middleware:
                broker.add_middleware(dlq_middleware)
            dramatiq.set_broker(broker)
            log.info("dramatiq.stub_broker_active")
        return dramatiq
    except ImportError:
        return None


_dramatiq = _setup_broker()

# ── Actor definitions ─────────────────────────────────────────────────────────

if _dramatiq is not None:

    @_dramatiq.actor(max_retries=2, time_limit=3600_000)  # type: ignore[untyped-decorator]
    def enqueue_bulk_download(year: int, month: int) -> None:
        """Descarga el bulk XML de un mes completo en background."""
        from scraper.bulk_downloader import download_month

        log.info("queue.bulk_download.start", year=year, month=month)
        result = download_month(year, month, force=False)
        log.info("queue.bulk_download.done", path=str(result))

    @_dramatiq.actor(max_retries=1, time_limit=7200_000)  # type: ignore[untyped-decorator]
    def enqueue_rebuild_embeddings() -> None:
        """Reconstruye el índice FAISS de embeddings en background."""
        import pandas as pd

        from services.faiss_index import FaissIndex
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

    def enqueue_bulk_download(year: int, month: int) -> None:
        """Inline fallback (dramatiq not installed)."""
        from scraper.bulk_downloader import download_month

        download_month(year, month, force=False)

    def enqueue_rebuild_embeddings() -> None:
        """Inline fallback (dramatiq not installed)."""
        import pandas as pd

        from services.faiss_index import FaissIndex
        from db.database import connect

        with connect() as c:
            cur = c.execute("SELECT id_externo, titulo, descripcion FROM licitaciones")
            cols = [d[0] for d in cur.description]
            df = pd.DataFrame(cur.fetchall(), columns=cols)
        idx = FaissIndex.build(df)
        idx.save()
