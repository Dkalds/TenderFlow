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
- ``fetch`` debe ser incremental respecto al cursor que recibe. ``new_cursor()``
  se consulta al final del fetch exitoso; además, para los conectores que
  declaran ``cursor_advances_incrementally = True``, tras cada lote persistido.
  Ese opt-in solo es correcto si el conector procesa de más viejo a más nuevo y
  ``new_cursor()`` refleja el progreso PARCIAL (p.ej. PSCP, para no reiniciar un
  fetch enorme si el job se corta). Un feed newest-first NO debe declararlo: su
  ``new_cursor()`` es el máximo global ya en el primer lote, y avanzarlo por lote
  perdería para siempre las entries viejas aún sin procesar si el run se corta.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from db.database import (
    get_cursor,
    replace_adjudicaciones_batch,
    replace_lotes_batch,
    set_cursor,
    upsert_licitaciones_with_history,
)
from db.dlq import record_failure
from observability import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

    from db.upsert import Adjudicacion, DocumentoReferencia, Licitacion, Lote

log = get_logger(__name__)

# Reintentos de un lote ante contención transitoria de Postgres (lock esperando
# a otro writer, deadlock, serialization failure). Observado en producción:
# el DELETE agrupado de replace_adjudicaciones_batch esperó el
# statement_timeout completo (30s) bloqueado detrás de otra transacción sobre
# la misma tabla `adjudicaciones` y tumbó el run entero pese a que la fila no
# tenía ningún problema real. `upsert_licitaciones_with_history` es idempotente
# (ADR-009), así que reintentar el flush completo -- no solo el paso que
# falló -- es seguro.
_FLUSH_MAX_ATTEMPTS = 3
_FLUSH_RETRY_BASE_S = 2.0


def _is_retryable_db_error(exc: BaseException) -> bool:
    """True si ``exc`` es un error transitorio de Postgres (lock/serialization).

    Deliberadamente NO incluye errores de conexión u otros ``OperationalError``
    genéricos: esos suelen ser permanentes dentro del mismo run (credenciales,
    red caída) y reintentarlos solo demora el fallo real.
    """
    try:
        from psycopg import errors as pg_errors
    except ImportError:
        return False
    return isinstance(
        exc,
        (
            pg_errors.QueryCanceled,
            pg_errors.LockNotAvailable,
            pg_errors.DeadlockDetected,
            pg_errors.SerializationFailure,
        ),
    )


def _record_source_started(source_id: str) -> None:
    """Best-effort: la observabilidad nunca bloquea la ingesta."""
    try:
        from db.repositories.source_health import SourceHealthRepository

        SourceHealthRepository().mark_started(source_id)
    except Exception:
        log.debug("connector_source_health_start_failed", source=source_id, exc_info=True)


def _record_source_completed(result: ConnectorRunResult) -> None:
    try:
        from db.repositories.source_health import SourceHealthRepository

        cursor = get_cursor(result.source_id) or {}
        status = "failed" if result.fetch_failed else "partial" if result.errores else "success"
        SourceHealthRepository().mark_completed(
            source=result.source_id,
            status=status,
            fetched=result.fetched,
            parsed=result.parsed,
            discarded=result.descartadas,
            errors=result.errores,
            cursor_value=str(cursor.get("last_seen_updated") or "") or None,
        )
    except Exception:
        log.debug("connector_source_health_finish_failed", source=result.source_id, exc_info=True)


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
    # Plan Pliegos+RAG (F6): referencias a adjuntos (pliegos) del CODICE.
    # Campo aditivo — connectores que no lo pueblan siguen funcionando igual
    # (default vacío, run_connector no persiste nada si la lista está vacía).
    documentos: list[DocumentoReferencia] = field(default_factory=list)
    # v65_lotes: lotes del expediente. Campo aditivo — connectores que no lo
    # pueblan siguen funcionando igual (adjudicaciones sin lote_numero_raw
    # resuelven lote_id=None, el "lote único implícito" de siempre).
    lotes: list[Lote] = field(default_factory=list)


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
    # IDs afectados por el upsert — mismo contrato que UpsertResult, para que
    # los wrappers de pipeline_runs puedan exponer el shape del pipeline legacy
    # (listas de id_externo, no solo contadores).
    inserted_ids: list[str] = field(default_factory=list)
    modified_ids: list[str] = field(default_factory=list)
    # True solo si fetch() abortó con excepción (fallo fatal de la fuente).
    # Los errores por-aviso (parse → DLQ) NO lo activan: esos son recuperables
    # y no deben marcar el run entero como fallido.
    fetch_failed: bool = False

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


def _persist_documentos(
    docs_por_lic: dict[str, list[DocumentoReferencia]], *, source_id: str
) -> None:
    """Persiste metadatos de adjuntos (plan Pliegos+RAG, F6). Fail-open: un
    fallo aquí no debe tumbar la ingesta de licitaciones/adjudicaciones, que
    ya se persistieron antes de llamar a esta función."""
    try:
        from db.repositories.documentos import DocumentosRepository

        repo = DocumentosRepository()
        for licitacion_id, refs in docs_por_lic.items():
            repo.upsert_meta(licitacion_id, refs)
    except Exception as e:
        log.warning("connector_documentos_persist_failed", source=source_id, error=str(e))


def _post_ingestion(source_id: str) -> None:
    """Resolución de empresas + dedupe + eventos de contrato + caché. Fail-open."""
    try:
        from services.entity_resolution import HOOK_TIME_BUDGET_S, resolve_all_unlinked

        # Acotado a la propia fuente (`scope_fuente`), reanudable (`resume`) y
        # con presupuesto de tiempo. Hasta 2026-08 era `resolve_all_unlinked(
        # fuente=source_id)` a secas, y las tres cosas faltaban: `fuente` solo
        # etiquetaba los aliases, así que cada conector barría la tabla entera
        # desde el id 0. Ingerir 112 avisos de TED arrancaba un recorrido del
        # millón largo de filas pendientes de PSCP, se comía los 10 min del
        # step y moría por SIGKILL antes de llegar al dedupe y a los eventos
        # de contrato de más abajo -- que estuvieron una semana sin correr.
        # `source_id` vale como ámbito porque los conectores respetan la
        # invariante `Licitacion.fuente = source_id` (ver docstring del módulo).
        resolve_all_unlinked(
            fuente=source_id,
            scope_fuente=source_id,
            resume=True,
            time_budget_s=HOOK_TIME_BUDGET_S,
        )
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
    _record_source_started(source_id)
    log.info("connector_run_start", source=source_id, cursor=cursor)

    # Colección del lote pendiente keyed por id_externo (no una lista): colapsa
    # el mismo expediente publicado varias veces dentro del run quedándose con la
    # versión más reciente. Sin esto, un feed newest-first trae el mismo aviso
    # varias veces y el `executemany ... ON CONFLICT DO UPDATE` procesa la lista
    # en orden → gana la ÚLTIMA = la más VIEJA (estado/importe/fecha_limite
    # regresados + filas de historial fantasma con diff nuevo→viejo).
    lic_por_id: dict[str, Licitacion] = {}
    adj_por_lic: dict[str, list[Adjudicacion]] = {}
    docs_por_lic: dict[str, list[DocumentoReferencia]] = {}
    lotes_por_lic: dict[str, list[Lote]] = {}
    # Mejor recencia (fecha_actualizacion_fuente) vista por id_externo en TODO el
    # run: persiste entre lotes para descartar reapariciones más viejas de un
    # expediente ya escrito en un flush anterior.
    mejor_recencia: dict[str, str] = {}

    def _flush_once() -> tuple[Any, int, int]:
        upsert_result = upsert_licitaciones_with_history(
            list(lic_por_id.values()), source=source_id
        )
        n_adj = n_failed = 0
        if lotes_por_lic:
            # Antes de persistir adjudicaciones: lote_id es un FK real a
            # lotes.id (autoincrement), así que hace falta el id que acaba de
            # asignar replace_lotes_batch para resolver lote_numero_raw en
            # cada Adjudicacion del mismo lote de escritura.
            lote_ids_por_lic = replace_lotes_batch(lotes_por_lic)
            for licitacion_id, mapping in lote_ids_por_lic.items():
                if not mapping:
                    continue
                for adj in adj_por_lic.get(licitacion_id, ()):
                    if adj.lote_numero_raw is not None:
                        adj.lote_id = mapping.get(adj.lote_numero_raw)
        if adj_por_lic:
            n_adj, n_dropped, n_failed = replace_adjudicaciones_batch(
                adj_por_lic, run_id=None, fuente=source_id
            )
            if n_dropped:
                log.warning("adj_rows_dropped", dropped=n_dropped, persisted=n_adj)
        if docs_por_lic:
            _persist_documentos(docs_por_lic, source_id=source_id)
        return upsert_result, n_adj, n_failed

    def _flush() -> None:
        if not lic_por_id:
            return
        # Reintenta el lote completo (no solo el paso que falló): tanto el
        # upsert de licitaciones como el replace de adjudicaciones son
        # idempotentes, así que repetirlos contra el mismo batch es seguro. El
        # resultado sólo se vuelca a `result` tras el intento que finalmente
        # tiene éxito, para no contar dos veces nuevas/actualizadas/adjudicaciones
        # si un intento anterior falló a mitad de camino.
        attempt = 1
        while True:
            try:
                upsert_result, n_adj, n_failed = _flush_once()
                break
            except Exception as e:
                if attempt >= _FLUSH_MAX_ATTEMPTS or not _is_retryable_db_error(e):
                    raise
                wait_s = _FLUSH_RETRY_BASE_S * attempt
                log.warning(
                    "connector_flush_retry",
                    source=source_id,
                    attempt=attempt,
                    wait_s=wait_s,
                    error=str(e),
                )
                time.sleep(wait_s)
                attempt += 1
        result.nuevas += len(upsert_result.inserted)
        result.actualizadas += len(upsert_result.modified)
        result.inserted_ids.extend(upsert_result.inserted)
        result.modified_ids.extend(upsert_result.modified)
        result.adjudicaciones += n_adj
        result.errores += n_failed
        lic_por_id.clear()
        if advances_incrementally:
            # Feeds ASC (PSCP): un id no reaparece más viejo en un lote posterior
            # (el stream avanza monótono por updated_at), así que no hace falta
            # recordar la recencia entre lotes; limpiarla acota la memoria en
            # runs enormes (catch-up de ~1.86M filas). Los feeds newest-first la
            # conservan para deduplicar entre lotes.
            mejor_recencia.clear()
        adj_por_lic.clear()
        docs_por_lic.clear()
        lotes_por_lic.clear()
        # Avance de cursor por lote SOLO para conectores que lo declaran seguro
        # (``cursor_advances_incrementally``). Es correcto cuando ``new_cursor()``
        # refleja el progreso PARCIAL persistido (feeds procesados de más viejo a
        # más nuevo, p.ej. PSCP: dataset con republicación completa, ~1.86M filas,
        # imposible de recorrer entero dentro del timeout de un run). Para un feed
        # newest-first (ATOM/TED), ``new_cursor()`` es el máximo GLOBAL ya en el
        # primer lote: avanzarlo aquí saltaría al tope y una ejecución cortada a
        # mitad perdería para siempre las entries viejas aún sin procesar. Esos
        # conectores avanzan el cursor solo al final, tras persistir todo el fetch.
        if advances_incrementally:
            new_cursor = connector.new_cursor()
            if new_cursor:
                set_cursor(source_id, **new_cursor)

    # ¿El conector puede avanzar el cursor por lote (progreso parcial) o solo al
    # final del fetch? Opt-in por atributo; el default seguro es "solo al final"
    # (getattr evita forzar a todos los conectores a declararlo en el Protocol).
    advances_incrementally = bool(getattr(connector, "cursor_advances_incrementally", False))

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
            lic_id = parsed.licitacion.id_externo
            recencia = parsed.licitacion.fecha_actualizacion_fuente or ""
            mejor = mejor_recencia.get(lic_id)
            if mejor is not None and recencia <= mejor:
                # Ya vimos una versión igual o más reciente de este expediente en
                # el run (pendiente en el lote o ya persistida en un flush previo):
                # no la pisamos con una más vieja. Con esto, tanto en feeds
                # newest-first como ASC, gana siempre la versión más reciente.
                continue
            mejor_recencia[lic_id] = recencia
            lic_por_id[lic_id] = parsed.licitacion
            # Companion data sincronizada con la versión conservada: se reemplaza
            # (no se acumula) y se limpia con pop si viene vacía, para no mezclar
            # adjudicaciones/lotes/docs de dos versiones ni borrar en BD las
            # existentes con un replace vacío (los ids sin adj no entran al dict).
            if parsed.adjudicaciones:
                adj_por_lic[lic_id] = parsed.adjudicaciones
            else:
                adj_por_lic.pop(lic_id, None)
            if parsed.documentos:
                docs_por_lic[lic_id] = parsed.documentos
            else:
                docs_por_lic.pop(lic_id, None)
            if parsed.lotes:
                lotes_por_lic[lic_id] = parsed.lotes
            else:
                lotes_por_lic.pop(lic_id, None)
            if len(lic_por_id) >= batch_size:
                _flush()
        _flush()
    except Exception as e:
        # El cursor ya avanzó (en _flush) hasta el último lote persistido
        # con éxito; solo se pierde el progreso del lote aún sin flushear
        # en el momento del fallo -- la próxima corrida no reinicia desde cero.
        result.errores += 1
        result.fetch_failed = True
        record_failure(None, source_id, e, scope="fetch")
        log.error("connector_run_failed", source=source_id, error=str(e))
        _record_source_completed(result)
        return result

    # Avance de cursor final, SOLO en éxito: el ``except`` de fetch retorna antes
    # de llegar aquí, así que una ejecución cortada a mitad NO avanza el cursor y
    # la próxima corrida re-procesa desde el punto anterior (idempotente). Para
    # los conectores no incrementales (feeds newest-first) este es el único
    # avance; para los incrementales es idempotente (mismo valor que el último
    # lote ya persistido).
    final_cursor = connector.new_cursor()
    if final_cursor:
        set_cursor(source_id, **final_cursor)

    if result.parsed or result.adjudicaciones:
        _post_ingestion(source_id)

    log.info("connector_run_done", **result.as_dict())
    _record_source_completed(result)
    return result
