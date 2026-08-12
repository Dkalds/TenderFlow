"""Snapshot de los agregados globales del overview, sobre ``kpi_snapshots``.

``GET /analytics/overview`` sin filtros ejecutaba media docena de agregaciones
sobre la tabla completa en cada fallo de caché. Medido en producción el
2026-08-12: 22,3 s los KPIs, 30,9 s las CCAA cubiertas, 24,8 s la tasa de
anulación y 42,3 s los indicadores de adjudicaciones — cada una reteniendo una
conexión de las doce del pool mientras tanto.

Ninguno de esos números cambia entre ingestas, y la ingesta corre cada 4 h
(``scrape-daily.yml``), así que se calculan una vez por ciclo en el paso
``kpi_precompute`` del pipeline y el endpoint los lee de una tabla de unas
pocas filas. El desfase máximo es el que ya tenían los datos.

Sobre la tabla que se reutiliza: ``kpi_snapshots`` (v51) ya existía con este
propósito exacto y con reemplazo atómico en ``_persist_snapshots``, así que
esto no añade esquema. Las métricas ``ov_*`` conviven con las que ese job
escribía antes, pero **no son las mismas y no deben mezclarse**: las legacy
(``total_licitaciones``, ``importe_total``…) filtran
``analysis_universe = 'technology_observed'`` y el overview agrega sin ese
filtro. Por eso se recalculan aquí llamando a ``AggregateRepository``, que es
literalmente el mismo código que sirve el camino en vivo — la paridad no
depende de mantener dos SQL parecidos sincronizados a mano.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from db.database import connect_read
from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from db.repositories.base import loose_distinct_strings
from observability.logging import get_logger

log = get_logger(__name__)

OV_KPIS: Final = "ov_kpis"
OV_ADJ_INDICADORES: Final = "ov_adj_indicadores"
OV_TASA_ANULACION: Final = "ov_tasa_anulacion"
OV_IMPORTE_P75: Final = "ov_importe_p75"
OV_TOTAL_ACTIVAS: Final = "ov_total_activas"
META_CPV_VALUES: Final = "meta_cpv_values"

_DIMENSION: Final = "global"

# Tres ciclos de pipeline perdidos. Pasado eso el snapshot se ignora y se
# vuelve al cálculo en vivo: es lento, pero servir cifras de ayer como si
# fueran de hoy es peor que tardar.
_DEFAULT_MAX_AGE_S: Final = 12 * 3600

_OVERVIEW_METRICAS: Final = (
    OV_KPIS,
    OV_ADJ_INDICADORES,
    OV_TASA_ANULACION,
    OV_IMPORTE_P75,
    OV_TOTAL_ACTIVAS,
)

# Claves que cada JSON debe traer para considerarse utilizable. Se validan aquí
# y no en el servicio: un snapshot a medias tiene que degradar a cálculo en
# vivo, no reventar el endpoint con un KeyError.
_KPIS_KEYS: Final = ("total", "importe_total", "importe_medio", "organos")
_ADJ_KEYS: Final = ("hhi", "pct_oferta_unica", "lead_time_medio", "pct_pyme")


@dataclass(frozen=True)
class OverviewSnapshot:
    """Agregados globales precalculados, ya validados.

    Cada campo puede venir a ``None`` por separado: el consumidor recalcula en
    vivo solo esa pieza en vez de tirar el snapshot entero.
    """

    computed_at: str
    # Misma forma que ``AggregateRepository.overview_kpis``: total (int),
    # importe_total/importe_medio (float), organos (int).
    kpis: dict[str, Any] | None
    adj_indicadores: dict[str, float | None] | None
    tasa_anulacion: tuple[int, int] | None
    importe_p75: float | None
    total_activas: int | None


def _fila(
    metrica: str, *, valor: float | None = None, valor_text: str | None = None
) -> dict[str, Any]:
    """Fila en el formato que espera ``scheduler.kpi_precompute._persist_snapshots``."""
    return {
        "metrica": metrica,
        "dimension": _DIMENSION,
        "valor": valor,
        "valor_text": valor_text,
    }


def compute_overview_snapshot_rows(conn: Any) -> list[dict[str, Any]]:
    """Calcula las métricas ``ov_*`` y la lista de CPV, listas para persistir.

    Se llama desde ``scheduler/kpi_precompute.py``, que las añade a las suyas y
    las escribe con el mismo ``computed_at``. El SQL vive aquí y en
    ``AggregateRepository`` — nunca en ``scheduler/`` (ADR-022).

    Todo va por la ``conn`` que ya tiene abierta el precálculo: son seis
    consultas de lectura y abrirles conexiones propias mientras se sostiene la
    de escritura solo gasta slots del pool.

    La ventana de la tasa de anulación se ancla al momento del precálculo y no
    al de la petición. Son 365 días: que el borde se mueva unas horas no cambia
    el porcentaje de forma observable.
    """
    repo = AggregateRepository()
    sin_filtros = LicitacionesFilters()
    hace_365d_iso = (datetime.now(UTC) - timedelta(days=365)).isoformat()

    kpis = repo.overview_kpis(sin_filtros, conn=conn)
    adj = repo.overview_adjudicaciones_indicadores(conn=conn)
    anul, total_12m = repo.overview_tasa_anulacion(
        sin_filtros, hace_365d_iso=hace_365d_iso, conn=conn
    )
    p75 = repo.importe_p75(conn=conn)
    activas = repo.count_total_activas(conn=conn)
    cpv = loose_distinct_strings(conn, "licitaciones", "cpv")

    return [
        _fila(OV_KPIS, valor_text=json.dumps(kpis, ensure_ascii=False)),
        _fila(OV_ADJ_INDICADORES, valor_text=json.dumps(adj, ensure_ascii=False)),
        _fila(OV_TASA_ANULACION, valor_text=json.dumps({"anul": anul, "total": total_12m})),
        _fila(OV_IMPORTE_P75, valor=p75),
        _fila(OV_TOTAL_ACTIVAS, valor=float(activas)),
        _fila(META_CPV_VALUES, valor_text=json.dumps(cpv, ensure_ascii=False)),
    ]


def _read_metricas(
    metricas: tuple[str, ...], *, max_age_seconds: int
) -> tuple[str, dict[str, tuple[float | None, str | None]]] | None:
    """Lee las métricas pedidas y su ``computed_at``, o ``None`` si no sirven.

    ``DISTINCT ON`` porque la tabla no tiene unicidad por métrica: si un
    precálculo dejase filas de dos tandas, gana la más reciente.
    """
    sql = (
        "SELECT DISTINCT ON (metrica) metrica, valor, valor_text, computed_at "
        "FROM kpi_snapshots "
        "WHERE dimension = %s AND metrica = ANY(%s) "
        "ORDER BY metrica, computed_at DESC"
    )
    try:
        with connect_read() as c:
            rows = c.execute(sql, (_DIMENSION, list(metricas))).fetchall()
    except Exception:
        log.warning("kpi_snapshot_read_failed", exc_info=True)
        return None

    if len(rows) != len(metricas):
        log.info("kpi_snapshot_incompleto", encontradas=len(rows), esperadas=len(metricas))
        return None

    valores: dict[str, tuple[float | None, str | None]] = {}
    computed_at = ""
    for metrica, valor, valor_text, fila_computed_at in rows:
        valores[str(metrica)] = (
            float(valor) if valor is not None else None,
            str(valor_text) if valor_text is not None else None,
        )
        computed_at = max(computed_at, str(fila_computed_at))

    try:
        edad = (datetime.now(UTC) - datetime.fromisoformat(computed_at)).total_seconds()
    except ValueError:
        log.warning("kpi_snapshot_computed_at_ilegible", computed_at=computed_at)
        return None
    if edad > max_age_seconds:
        log.info("kpi_snapshot_caducado", edad_s=int(edad), max_age_s=max_age_seconds)
        return None
    return computed_at, valores


def _json_dict(raw: str | None, *, requiere: tuple[str, ...] = ()) -> dict[str, Any] | None:
    """Parsea un ``valor_text`` que debería ser un objeto JSON con ciertas claves."""
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        log.warning("kpi_snapshot_json_invalido")
        return None
    if not isinstance(parsed, dict):
        return None
    faltan = [k for k in requiere if k not in parsed]
    if faltan:
        log.warning("kpi_snapshot_claves_ausentes", faltan=faltan)
        return None
    return parsed


def read_overview_snapshot(*, max_age_seconds: int = _DEFAULT_MAX_AGE_S) -> OverviewSnapshot | None:
    """Devuelve el snapshot del overview, o ``None`` si no hay uno utilizable.

    ``None`` significa "calculalo en vivo", nunca un error: falta de datos,
    JSON corrupto o snapshot viejo son todos casos esperables —el pipeline
    todavía no ha corrido, o falló— y ninguno justifica un 500 en un endpoint
    que sabe calcular lo mismo por sí solo.
    """
    leido = _read_metricas(_OVERVIEW_METRICAS, max_age_seconds=max_age_seconds)
    if leido is None:
        return None
    computed_at, valores = leido

    tasa = _json_dict(valores[OV_TASA_ANULACION][1], requiere=("anul", "total"))
    tasa_par = (int(tasa["anul"]), int(tasa["total"])) if tasa is not None else None

    adj = _json_dict(valores[OV_ADJ_INDICADORES][1], requiere=_ADJ_KEYS)
    adj_tipado: dict[str, float | None] | None = None
    if adj is not None:
        adj_tipado = {k: (float(v) if v is not None else None) for k, v in adj.items()}

    activas_raw = valores[OV_TOTAL_ACTIVAS][0]
    return OverviewSnapshot(
        computed_at=computed_at,
        kpis=_json_dict(valores[OV_KPIS][1], requiere=_KPIS_KEYS),
        adj_indicadores=adj_tipado,
        tasa_anulacion=tasa_par,
        # `valor` NULL es legítimo aquí: corpus sin ningún importe. Se propaga
        # como None para que el llamante no aplique umbral, no como 0.0.
        importe_p75=valores[OV_IMPORTE_P75][0],
        total_activas=int(activas_raw) if activas_raw is not None else None,
    )


def read_overview_snapshot_for(
    filters: LicitacionesFilters, *, max_age_seconds: int = _DEFAULT_MAX_AGE_S
) -> OverviewSnapshot | None:
    """El snapshot, si es aplicable a ``filters``.

    Solo lo es cuando el ámbito es la tabla entera: lo precalculado son
    agregados globales, y aplicarlos a una pregunta filtrada daría números que
    no corresponden al filtro. Cualquier fallo devuelve ``None`` — leer el
    snapshot es una optimización, y ninguna optimización debe poder tumbar un
    endpoint que sabe calcular lo mismo por sí solo.
    """
    if not filters.is_empty():
        return None
    try:
        return read_overview_snapshot(max_age_seconds=max_age_seconds)
    except Exception:
        log.warning("kpi_snapshot_overview_no_disponible", exc_info=True)
        return None


def read_meta_cpv(*, max_age_seconds: int = _DEFAULT_MAX_AGE_S) -> list[str] | None:
    """Lista de CPV distintos precalculada, o ``None`` para recalcular en vivo.

    Es la única de las cuatro listas de ``/meta/filters`` que sigue siendo cara
    tras el loose index scan: 18.203 valores distintos son 18.203 descensiones
    por el btree, unos 9,5 s. Las otras tres bajaron a decenas de milisegundos
    y se siguen resolviendo en vivo.
    """
    leido = _read_metricas((META_CPV_VALUES,), max_age_seconds=max_age_seconds)
    if leido is None:
        return None
    raw = leido[1][META_CPV_VALUES][1]
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        log.warning("kpi_snapshot_cpv_json_invalido")
        return None
    if not isinstance(parsed, list):
        return None
    return [str(v) for v in parsed]
