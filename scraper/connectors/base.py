"""Contrato ``Connector`` y runner genérico de ingesta (ADR-009).

Una fuente nueva implementa dos métodos:

- ``fetch(cursor)``: descarga avisos crudos desde el estado del cursor
  (``ingestion_cursors``) y los emite como ``RawNotice``.
- ``parse(raw)``: mapea un aviso crudo al modelo canónico (``ParsedTender``:
  ``Licitacion`` + lista de ``Adjudicacion``), o ``None`` para descartarlo.

``run_connector`` aporta el resto — el mismo esqueleto probado del pipeline
PLACSP: upsert idempotente con historial, persistencia de adjudicaciones,
DLQ por aviso fallido, avance de cursor, resolución de empresas (v35) y
señal de invalidación de caché.

Invariantes que el conector debe respetar:
- ``id_externo`` namespaceado: ``f"{source_id}:{id_natural}"``.
- ``Licitacion.fuente = source_id``.
- ``fetch`` debe ser incremental respecto al cursor que recibe; ``new_cursor()``
  debe reflejar el progreso visto hasta el momento en que se lo llama (el
  runner lo consulta después de cada lote persistido, no solo al final) --
  para que una ejecución cortada a mitad de camino (timeout externo del job)
  no pierda todo el avance y la próxima corrida pueda retomar desde ahí.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from db.database import (
    get_cursor,
    replace_adjudicaciones_batch,
    set_cursor,
    upsert_licitaciones_with_history,
)
from db.dlq import record_failure
from observability import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

    from db.upsert import Adjudicacion, Licitacion

log = get_logger(__name__)


@dataclass
class RawNotice:
    """Aviso crudo tal como llega de la fuente.

    ``natural_id`` es el identificador en la fuente (sin namespace);
    ``payload`` el documento ya decodificado (dict para APIs JSON, bytes/str
    para XML) que ``parse`` sabrá interpretar.
    """

    natural_id: str
    payload: Any


@dataclass
class ParsedTender:
    licitacion: Licitacion
    adjudicaciones: list[Adjudicacion] = field(default_factory=list)


@runtime_checkable
class Connector(Protocol):
    """Contrato mínimo de una fuente de ingesta."""

    @property
    def source_id(self) -> str:
        """Identificador de la fuente. Solo lectura -- nunca se reasigna."""
        ...

    def fetch(self, cursor: dict[str, Any] | None) -> Iterator[RawNotice]:
        """Emite avisos crudos nuevos/modificados desde el estado del cursor."""
        ...

    def parse(self, raw: RawNotice) -> ParsedTender | None:
        """Mapea al modelo canónico; None descarta el aviso (no relevante)."""
        ...

    def new_cursor(self) -> dict[str, Any] | None:
        """Estado de cursor a persistir si la ejecución acaba sin error fatal.

        Claves aceptadas: ``last_seen_updated``, ``last_entry_id``, ``etag``,
        ``last_modified`` (las de ``ingestion_cursors``). None = no avanzar.
        """
        ...


@dataclass
class ConnectorRunResult:
    source_id: str
    fetched: int = 0
    parsed: int = 0
    descartadas: int = 0
    nuevas: int = 0
    actualizadas: int = 0
    adjudicaciones: int = 0
    errores: int = 0

    def as_dict(self) -> dict[str, int | str]:
        return {
            "source_id": self.source_id,
            "fetched": self.fetched,
            "parsed": self.parsed,
            "descartadas": self.descartadas,
            "nuevas": self.nuevas,
            "actualizadas": self.actualizadas,
            "adjudicaciones": self.adjudicaciones,
            "errores": self.errores,
        }


def _post_ingestion(source_id: str) -> None:
    """Resolución de empresas + dedupe + eventos de contrato + caché. Fail-open."""
    try:
        from services.entity_resolution import resolve_unlinked_adjudicaciones

        resolve_unlinked_adjudicaciones(fuente=source_id)
    except Exception as e:
        log.warning("connector_entity_resolution_failed", source=source_id, error=str(e))
    try:
        from services.dedupe import detect_duplicates

        detect_duplicates(fuente=source_id)
    except Exception as e:
        log.warning("connector_dedupe_failed", source=source_id, error=str(e))
    try:
        from services.contract_events import derive_new_events

        derive_new_events()
    except Exception as e:
        log.warning("connector_contract_events_failed", source=source_id, error=str(e))
    try:
        from shared.cache_signal import signal_cache_invalidation

        signal_cache_invalidation()
    except Exception:
        log.debug("connector_cache_signal_failed", source=source_id)


def run_connector(connector: Connector, *, batch_size: int = 200) -> ConnectorRunResult:
    """Ejecuta un ciclo completo de ingesta para una fuente.

    Procesa en lotes de ``batch_size`` para acotar transacciones. Un aviso
    que falla al parsear va a la DLQ y no interrumpe el resto. El cursor
    avanza después de cada lote persistido con éxito (no solo al final):
    un fallo en ``fetch`` -- o una interrupción externa por timeout del job,
    que no es una excepción Python y corta el proceso a mitad de camino --
    conserva el progreso hasta el último lote; la próxima ejecución retoma
    desde ahí en vez de reiniciar siempre desde el mismo punto.
    """
    source_id = connector.source_id
    result = ConnectorRunResult(source_id=source_id)
    cursor = get_cursor(source_id)
    log.info("connector_run_start", source=source_id, cursor=cursor)

    lics: list[Licitacion] = []
    adj_por_lic: dict[str, list[Adjudicacion]] = {}

    def _flush() -> None:
        if not lics:
            return
        upsert_result = upsert_licitaciones_with_history(lics, source=source_id)
        result.nuevas += len(upsert_result.inserted)
        result.actualizadas += len(upsert_result.modified)
        if adj_por_lic:
            n_adj, n_dropped, n_failed = replace_adjudicaciones_batch(
                adj_por_lic, run_id=None, fuente=source_id
            )
            result.adjudicaciones += n_adj
            result.errores += n_failed
            if n_dropped:
                log.warning("adj_rows_dropped", dropped=n_dropped, persisted=n_adj)
        lics.clear()
        adj_por_lic.clear()
        # Avanzar el cursor por cada lote persistido, no solo al final del
        # fetch completo. Si la ejecución se corta a mitad de camino (timeout
        # externo del job, no una excepción Python), el progreso hasta el
        # último lote queda guardado y la próxima corrida retoma desde ahí en
        # vez de reiniciar siempre desde el mismo punto (ver PSCP: dataset con
        # republicación completa, ~1.86M filas, imposible de recorrer entero
        # dentro del timeout de un solo run).
        new_cursor = connector.new_cursor()
        if new_cursor:
            set_cursor(source_id, **new_cursor)

    try:
        for raw in connector.fetch(cursor):
            result.fetched += 1
            try:
                parsed = connector.parse(raw)
            except Exception as e:
                result.errores += 1
                record_failure(None, source_id, e, scope="parse", payload_ref=raw.natural_id)
                continue
            if parsed is None:
                result.descartadas += 1
                continue
            result.parsed += 1
            lics.append(parsed.licitacion)
            if parsed.adjudicaciones:
                adj_por_lic[parsed.licitacion.id_externo] = parsed.adjudicaciones
            if len(lics) >= batch_size:
                _flush()
        _flush()
    except Exception as e:
        # El cursor ya avanzó (en _flush) hasta el último lote persistido
        # con éxito; solo se pierde el progreso del lote aún sin flushear
        # en el momento del fallo -- la próxima corrida no reinicia desde cero.
        result.errores += 1
        record_failure(None, source_id, e, scope="fetch")
        log.error("connector_run_failed", source=source_id, error=str(e))
        return result

    if result.parsed or result.adjudicaciones:
        _post_ingestion(source_id)

    log.info("connector_run_done", **result.as_dict())
    return result
