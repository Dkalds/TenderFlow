"""Data quality analytics — completeness metrics, scrape freshness.

Agrega en Postgres vía :class:`AggregateRepository` (ADR-023). Además de
retirar la carga full-table (bloqueada en Render), esto CIERRA el ítem del
backlog «quality.py ya no detecta fechas legacy malformadas»: el check ISO
opera en SQL sobre el string crudo de ``fecha_publicacion``, que el camino
pandas perdía al convertir la columna a ``Timestamp``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
from pydantic import BaseModel, Field

from db.repositories.aggregates import AggregateRepository
from observability.logging import get_logger

log = get_logger(__name__)

_repo = AggregateRepository()


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class ColumnCompleteness(BaseModel):
    """Completeness for a single column."""

    columna: str
    pct: float


class AdjudicacionesPorFuente(BaseModel):
    """Cobertura de los campos de adjudicación en UNA fuente de ingesta (C4.7).

    Existe porque promediar estas cifras entre fuentes miente: medido contra
    producción el 2026-09-06, PLACSP trae el 100 % de `n_ofertas_recibidas` y
    PSCP el 37 %, y ni PSCP ni TED traen **nada** de rango de oferta ni de PYME.
    Un «57 % de cobertura de PYME» global es la media de un 57 % real y de dos
    ceros, y no describe a ninguna de las tres.
    """

    fuente: str
    filas: int
    pct_n_ofertas: float
    pct_oferta_minima: float
    pct_oferta_maxima: float
    pct_es_pyme: float


class QualityResult(BaseModel):
    """Data quality metrics."""

    total_records: int = 0
    pct_cpv: float = 0.0
    pct_importe: float = 0.0
    pct_fecha: float = 0.0
    pct_titulo: float = 0.0
    last_scrape_hours_ago: float | None = None
    dlq_count: int = 0
    completitud_columnas: list[ColumnCompleteness] = Field(default_factory=list)
    # `None` = NO MEDIDO, y la tarjeta se abstiene. Ni `nif` ni `modulo_sap` son
    # columnas de `licitaciones`: el camino pandas caía en el guard
    # `if col in df.columns` y la migración a SQL congeló ese resultado como el
    # literal 0.0. En la pantalla que existe para acreditar la calidad del dato,
    # publicar un 0,0 % medido de una cobertura que nadie mide es peor que no
    # publicar nada — y el 0.0 pasaba la guarda `!= null` del frontend.
    cobertura_nif: float | None = None
    cobertura_modulo_sap: float | None = None
    # Consistencia de FORMATO de fecha (no completitud): de las fechas de
    # publicación presentes, % en ISO-8601 y nº con formato inválido (DD/MM/YYYY…).
    pct_fecha_iso: float = 0.0
    fechas_no_iso: int = 0
    # Cobertura de tenencia por organización (v64) sobre las 7 tablas
    # user-scoped que la soportan. Métrica de cuándo se puede retirar el
    # scope legacy user_key-only (ver docs/IMPROVEMENT_BACKLOG.md).
    pct_organization_scoped: float = 100.0
    filas_sin_organizacion: int = 0
    # C4.7 — completitud de adjudicaciones POR FUENTE. Lista vacía = no medido
    # (la consulta falló o no hay adjudicaciones), no «todo a cero»: la misma
    # regla que `cobertura_nif` unas líneas más arriba.
    adjudicaciones_por_fuente: list[AdjudicacionesPorFuente] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _last_scrape_hours() -> float | None:
    """Get hours since last extraction run, if available."""
    try:
        from services.extraction_runs import load_runs

        runs = load_runs(limit=1)
        if not runs:
            return None
        last = runs[0]
        ended = last.get("ended_at") or last.get("started_at")
        if not ended:
            return None
        if isinstance(ended, str):
            ts = pd.to_datetime(ended, utc=True)
        else:
            ts = pd.Timestamp(ended, tz="UTC")
        delta = datetime.now(UTC) - ts.to_pydatetime()
        return round(delta.total_seconds() / 3600, 2)
    except Exception:
        log.debug("quality_last_scrape_unavailable")
        return None


def _dlq_count() -> int:
    """Número real de fallos abiertos en la DLQ (best-effort).

    Antes era un stub que devolvía 0: el panel mostraba siempre 0 fallos aunque
    la cola tuviera registros perdidos. Ahora consulta ``failed_extractions``.
    """
    try:
        from db.dlq import count_unresolved

        return count_unresolved()
    except Exception:
        log.debug("quality_dlq_count_unavailable")
        return 0


def _organization_scope_coverage() -> tuple[float, int]:
    """(% de filas con organization_id, nº sin organization_id) en las 7
    tablas escopadas por v64. Independiente de ``licitaciones``."""
    try:
        from db.repositories.organizations import OrganizationRepository

        coverage = OrganizationRepository().scope_coverage()
        total = coverage["total"]
        sin_organizacion = coverage["sin_organizacion"]
        pct = 100.0 if total == 0 else (total - sin_organizacion) / total * 100
        return pct, sin_organizacion
    except Exception:
        log.debug("quality_organization_scope_unavailable")
        return 100.0, 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _adjudicaciones_por_fuente() -> list[AdjudicacionesPorFuente]:
    """Cobertura por fuente, tolerante a fallo.

    Un error aquí no puede tumbar la pantalla entera de calidad del dato: se
    devuelve la lista vacía y el resto de métricas se sirve igual, que es el
    mismo criterio que `_dlq_count`.
    """
    from db.repositories.adjudicaciones import completitud_por_fuente

    try:
        filas = completitud_por_fuente()
    except Exception:
        log.warning("analytics_quality_adjudicaciones_por_fuente_fallo", exc_info=True)
        return []

    salida: list[AdjudicacionesPorFuente] = []
    for fila in filas:
        n = int(fila.get("filas") or 0)
        if n <= 0:
            continue

        def _pct(clave: str, total: int = n, f: dict = fila) -> float:
            return round(100.0 * int(f.get(clave) or 0) / total, 1)

        salida.append(
            AdjudicacionesPorFuente(
                fuente=str(fila.get("fuente") or "(sin fuente)"),
                filas=n,
                pct_n_ofertas=_pct("con_n_ofertas"),
                pct_oferta_minima=_pct("con_oferta_minima"),
                pct_oferta_maxima=_pct("con_oferta_maxima"),
                pct_es_pyme=_pct("con_es_pyme"),
            )
        )
    return salida


def get_quality() -> QualityResult:
    """Compute data quality metrics (agregación SQL, ADR-023)."""
    log.info("analytics_quality_start")
    stats = _repo.quality_completitud()
    pct_organization_scoped, filas_sin_organizacion = _organization_scope_coverage()

    total = stats["total"]
    if total == 0:
        log.info("analytics_quality_done", total=0)
        return QualityResult(
            dlq_count=_dlq_count(),
            pct_organization_scoped=pct_organization_scoped,
            filas_sin_organizacion=filas_sin_organizacion,
        )

    cols: dict[str, int] = stats["cols"]

    def _pct(n: int) -> float:
        return float(n / total * 100)

    fechas_presentes = cols.get("fecha_publicacion", 0)
    fecha_iso = stats["fecha_iso"]
    pct_fecha_iso = float(fecha_iso / fechas_presentes * 100) if fechas_presentes else 0.0

    completitud = [
        ColumnCompleteness(columna=col, pct=_pct(cols[col]))
        for col in (
            "id_externo",
            "titulo",
            "organo_contratacion",
        )
    ]
    completitud.append(ColumnCompleteness(columna="importe", pct=_pct(stats["importe"])))
    completitud.extend(
        ColumnCompleteness(columna=col, pct=_pct(cols[col]))
        for col in (
            "estado",
            "fecha_publicacion",
            "ccaa",
            "cpv",
            "url",
            "tecnologia",
            "tipo_contrato",
            "provincia",
        )
    )

    result = QualityResult(
        total_records=total,
        pct_cpv=_pct(cols.get("cpv", 0)),
        pct_importe=_pct(stats["importe"]),
        pct_fecha=_pct(fechas_presentes),
        pct_titulo=_pct(cols.get("titulo", 0)),
        pct_fecha_iso=pct_fecha_iso,
        fechas_no_iso=int(fechas_presentes - fecha_iso),
        last_scrape_hours_ago=_last_scrape_hours(),
        dlq_count=_dlq_count(),
        pct_organization_scoped=pct_organization_scoped,
        filas_sin_organizacion=filas_sin_organizacion,
        completitud_columnas=completitud,
        adjudicaciones_por_fuente=_adjudicaciones_por_fuente(),
        # cobertura_nif / cobertura_modulo_sap se quedan en su default `None`
        # (no medidas): ver la nota del DTO.
    )
    log.info("analytics_quality_done", total=result.total_records)
    return result
