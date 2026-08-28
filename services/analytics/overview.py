"""Analytics overview service for aggregated tender KPIs and breakdowns.

Las agregaciones (KPIs, breakdowns por estado/mes/organo, indicadores de
mercado) se calculan en Postgres vía ``db.repositories.aggregates`` — antes se
cargaba la tabla ``licitaciones`` completa (~47k filas) a pandas y se
agregaba en el proceso web (capado a 4 hilos, ver ``api/app.py`` y el
postmortem de ``services/_data_cache.py``). Postgres resuelve estos
``GROUP BY`` en milisegundos.

``hhi``/``pct_oferta_unica``/``lead_time_medio`` se agregan también en
Postgres (``overview_adjudicaciones_indicadores``) — antes venían del
DataFrame full-table de ``load_adjudicaciones()`` (27 s y ~170k filas por
llamada medidos en prod), que en Render además estaba bloqueado por
``render_api_full_table_loads_blocked`` y dejaba los tres KPIs a cero/None.
Siguen ignorando los filtros del endpoint, como siempre hicieron.

``pct_oferta_unica`` y ``pct_pyme`` viajan además con su cobertura
(``CoberturaMetricaDTO``). El motivo: en producción la tira de salud
competitiva del Resumen publicaba «oferta única 93,1 %» y «PYME adjudicataria
0,7 %», dos cifras que nadie del dominio se cree. No son el mercado español,
son el reparto de qué filas traen ``n_ofertas_recibidas`` y ``es_pyme`` — la
republicación masiva de PSCP no los trae. Sin denominador, un porcentaje así
describe la fuente, no el fenómeno. La cobertura de ``pct_oferta_unica`` ya sale
medida —el agregado de ``db/`` cuenta su base y su universo—; la de ``pct_pyme``
sigue **desconocida** a propósito hasta que el denominador de esa métrica y el
de su cobertura sean el mismo (ver ``_K_ADJ_*``), y desconocida basta para que
el consumidor se abstenga.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Final

from pydantic import BaseModel, Field

from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from db.repositories.kpi_snapshots import read_overview_snapshot_for
from observability.logging import get_logger
from shared.dto import CoberturaMetricaDTO

log = get_logger(__name__)

_repo = AggregateRepository()

#: Umbral de cobertura por debajo del cual un porcentaje agregado deja de ser un
#: hecho del mercado y pasa a ser un hecho sobre qué filas traen el campo.
#:
#: 50 % es el punto en que la muestra deja de ser mayoría del corpus: por debajo,
#: el sesgo de selección de la fuente puede mover el resultado más que el
#: fenómeno medido. No es un umbral estadístico —no hay uno que valga para
#: cualquier campo—, es el mínimo defendible ante alguien del dominio: «lo
#: calculo sobre menos de la mitad de las adjudicaciones» ya obliga a explicarse.
UMBRAL_COBERTURA_PCT: Final = 50.0

#: Claves de cobertura de ``overview_adjudicaciones_indicadores``.
#:
#: Las dos primeras **ya llegan**: el agregado de ``db/repositories`` cuenta las
#: adjudicaciones totales y las que declaran ``n_ofertas_recibidas``, así que la
#: cobertura de ``pct_oferta_unica`` es un número medido y la celda deja de
#: abstenerse por falta de dato.
#:
#: La tercera **sigue sin llegar, y a propósito**: ``pct_pyme`` divide entre
#: ``COUNT(*)`` —el NULL cuenta como «no PYME»— mientras que su cobertura
#: mediría las filas que sí declaran ``es_pyme``. Valor y cobertura hablarían de
#: bases distintas, y destaparla sin corregir antes el denominador en ``db/``
#: sería pasar de ocultar un número dudoso a publicarlo. Hasta entonces la
#: métrica se abstiene, que es el default correcto.
#:
#: Se leen todas con ``.get`` por lo mismo de siempre: una clave que falte tiene
#: que dar cobertura desconocida, nunca un cero que parezca medido.
_K_ADJ_TOTAL: Final = "adj_total"
_K_ADJ_CON_N_OFERTAS: Final = "adj_con_n_ofertas"
_K_ADJ_CON_ES_PYME: Final = "adj_con_es_pyme"


def _cobertura_desconocida() -> CoberturaMetricaDTO:
    """Cobertura sin medir: ``suficiente=False``, que es el default seguro."""
    return CoberturaMetricaDTO(umbral_pct=UMBRAL_COBERTURA_PCT)


def _cobertura(base: float | None, universo: float | None) -> CoberturaMetricaDTO:
    """Cobertura de un porcentaje a partir de su base y su universo.

    ``cobertura_pct`` no se redondea: un 3,4 % tiene que salir como 3,4 % para
    que el consumidor pueda decir cuánto de poco es. Redondearlo a algo cómodo
    —a cero, al umbral, a «bajo»— sería repetir el problema que este campo viene
    a resolver. El único ajuste es el tope en 100, que solo puede saltar si base
    y universo llegan de consultas incoherentes; el DTO lo exige (``le=100``) y
    reventar aquí por eso sería tumbar el overview entero por un decimal.

    Un universo a cero **no** es cobertura 100 %: es que no hay corpus que medir,
    y se devuelve como desconocida.
    """
    if base is None or universo is None or universo <= 0:
        return _cobertura_desconocida()
    pct = min(base / universo * 100, 100.0)
    return CoberturaMetricaDTO(
        base=int(base),
        universo=int(universo),
        cobertura_pct=pct,
        umbral_pct=UMBRAL_COBERTURA_PCT,
        suficiente=pct >= UMBRAL_COBERTURA_PCT,
    )


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class OverviewFilters(BaseModel):
    """Query filters for the overview endpoint."""

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None
    estado: str | None = None
    q: str | None = None
    importe_min: float | None = None


class EstadoCount(BaseModel):
    """Count per estado."""

    estado: str
    n: int


class MesAggregate(BaseModel):
    """Monthly aggregate."""

    mes: str
    n_licitaciones: int
    importe: float


class OrganoAggregate(BaseModel):
    """Top organo aggregate."""

    organo_contratacion: str
    n: int
    importe: float


class FunnelStep(BaseModel):
    """Funnel step with absolute count and percentage."""

    estado: str
    n: int
    pct: float


class OverviewResult(BaseModel):
    """Combined overview response."""

    total_licitaciones: int = 0
    importe_total: float = 0.0
    importe_medio: float = 0.0
    organos_unicos: int = 0
    yoy_delta: float = 0.0
    licitaciones_30d: int = 0
    importe_30d: float = 0.0
    por_estado: list[EstadoCount] = Field(default_factory=list)
    por_mes: list[MesAggregate] = Field(default_factory=list)
    top_organos: list[OrganoAggregate] = Field(default_factory=list)
    funnel_estados: list[FunnelStep] = Field(default_factory=list)
    hhi: float = 0.0
    pct_oferta_unica: float = 0.0
    # Market indicators
    pct_pyme: float = 0.0
    # Cada uno de los dos porcentajes de arriba viaja con las filas que lo
    # sostienen. Campos nuevos con default: el contrato existente no se rompe y
    # un cliente que los ignore ve exactamente lo que veía antes — por eso el
    # gate vive en el consumidor y no en el valor, que se sigue sirviendo.
    cobertura_oferta_unica: CoberturaMetricaDTO = Field(default_factory=_cobertura_desconocida)
    cobertura_pyme: CoberturaMetricaDTO = Field(default_factory=_cobertura_desconocida)
    concentracion_top10: float = 0.0
    lead_time_medio: float | None = None
    tasa_anulacion: float = 0.0
    concentracion_geo_top3: float = 0.0
    ccaa_cubiertas: int = 0
    # "Para hoy" counts
    calientes_hoy: int = 0
    vencen_48h: int = 0
    nuevas_24h: int = 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_repo_filters(filters: OverviewFilters) -> LicitacionesFilters:
    return LicitacionesFilters(
        ccaa=filters.ccaa,
        tecnologia=filters.tecnologia,
        estado=filters.estado,
        fecha_desde=filters.fecha_desde.isoformat() if filters.fecha_desde else None,
        fecha_hasta=filters.fecha_hasta.isoformat() if filters.fecha_hasta else None,
        importe_min=filters.importe_min,
        q=filters.q,
    )


def _adj_indicadores() -> dict[str, float | None]:
    """HHI, % oferta única, lead time medio y % PYME — en Postgres, sin filtros."""
    try:
        return _repo.overview_adjudicaciones_indicadores()
    except Exception:
        log.warning("overview_adj_indicadores_failed", exc_info=True)
        return {
            "hhi": 0.0,
            "pct_oferta_unica": 0.0,
            "lead_time_medio": None,
            "pct_pyme": 0.0,
        }


def get_overview(filters: OverviewFilters) -> OverviewResult:
    """Compute the full overview payload — agregaciones vía SQL en Postgres."""
    log.info("analytics_overview_start", filters=filters.model_dump(exclude_none=True))
    repo_filters = _to_repo_filters(filters)

    # Sin filtros, los agregados sobre la tabla completa vienen del snapshot que
    # deja el pipeline de ingesta: entre scrapes no cambian, y calcularlos aquí
    # costaba 22 s (KPIs), 25 s (tasa de anulación) y 42 s (adjudicaciones) por
    # cada fallo de caché. Cada pieza cae por su cuenta al cálculo en vivo si
    # falta, así que un snapshot incompleto degrada en vez de romper.
    snap = read_overview_snapshot_for(repo_filters)
    snap_kpis = snap.kpis if snap is not None else None
    snap_adj = snap.adj_indicadores if snap is not None else None
    snap_tasa = snap.tasa_anulacion if snap is not None else None

    adj_ind = snap_adj if snap_adj is not None else _adj_indicadores()
    k = snap_kpis if snap_kpis is not None else _repo.overview_kpis(repo_filters)

    hoy = datetime.now(UTC)
    hace_30d_iso = (hoy - timedelta(days=30)).isoformat()
    hace_60d_iso = (hoy - timedelta(days=60)).isoformat()
    hace_365d_iso = (hoy - timedelta(days=365)).isoformat()
    hace_24h_iso = (hoy - timedelta(hours=24)).isoformat()
    hoy_iso = hoy.isoformat()
    limite_48h_iso = (hoy + timedelta(hours=48)).isoformat()

    yoy_data = _repo.overview_yoy_and_recent(
        repo_filters, hace_30d_iso=hace_30d_iso, hace_60d_iso=hace_60d_iso
    )
    v_act = yoy_data["lics_30d"]
    v_prev = yoy_data["lics_prev30d"]
    yoy = ((v_act - v_prev) / v_prev * 100) if v_prev else 0.0

    # --- Market indicators ---
    top10_imp, total_imp = _repo.overview_concentracion_organos(repo_filters, top_n=10)
    total_imp = total_imp or 1.0
    concentracion_top10 = top10_imp / total_imp * 100

    anul_count, total_12m = (
        snap_tasa
        if snap_tasa is not None
        else _repo.overview_tasa_anulacion(repo_filters, hace_365d_iso=hace_365d_iso)
    )
    tasa_anulacion = (anul_count / total_12m * 100) if total_12m > 0 else 0.0

    top3_imp, total_imp_geo = _repo.overview_concentracion_ccaa(repo_filters, top_n=3)
    total_imp_geo = total_imp_geo or 1.0
    concentracion_geo_top3 = top3_imp / total_imp_geo * 100

    ccaa_cubiertas = _repo.overview_ccaa_cubiertas(repo_filters)

    para_hoy = _repo.overview_para_hoy(
        repo_filters,
        hoy_iso=hoy_iso,
        limite_48h_iso=limite_48h_iso,
        hace_24h_iso=hace_24h_iso,
        p75=snap.importe_p75 if snap is not None else None,
        total_activas=snap.total_activas if snap is not None else None,
    )

    por_estado = [
        EstadoCount(estado=row["estado"], n=int(row["n"]))
        for row in _repo.overview_por_estado(repo_filters)
    ]
    por_mes = [
        MesAggregate(
            mes=row["mes"], n_licitaciones=int(row["n_licitaciones"]), importe=float(row["importe"])
        )
        for row in _repo.overview_por_mes(repo_filters)
    ]
    top_organos = [
        OrganoAggregate(
            organo_contratacion=row["organo_contratacion"],
            n=int(row["n"]),
            importe=float(row["importe"]),
        )
        for row in _repo.overview_top_organos(repo_filters)
    ]

    funnel_data = _repo.overview_funnel(repo_filters)
    total_funnel = funnel_data["total"]

    def _paso(estado: str, n: int) -> FunnelStep:
        return FunnelStep(
            estado=estado,
            n=n,
            pct=float(n / total_funnel * 100) if total_funnel else 0.0,
        )

    # AGR, EJEC y CPM son los códigos de la PSCP catalana que normalizó v91, y
    # AGR solo es el 93% del corpus: sin ellos estos tramos sumaban una fracción
    # del total y la pantalla no lo decía.
    codigos = ("PUB", "EV", "RES", "ADJ", "ANUL", "PRE", "AGR", "EJEC", "CPM")
    funnel_estados = [_paso(est, funnel_data.get(est, 0)) for est in codigos]

    # Y lo que no cae en ninguno —filas sin estado, o con el texto crudo que el
    # conector escribió antes del arreglo y que la reparación aún no ha
    # limpiado— se declara en vez de desaparecer. El tramo solo aparece si hay
    # algo dentro, así que sobre un corpus limpio nada cambia. Que los tramos
    # sumen el total es la propiedad que hace legible el embudo: sin ella, quien
    # lo mira no puede saber si lo que falta es cero o es un millón de filas.
    resto = total_funnel - sum(funnel_data.get(est, 0) for est in codigos)
    if resto > 0:
        funnel_estados.append(_paso("OTROS", resto))

    result = OverviewResult(
        total_licitaciones=k["total"],
        importe_total=k["importe_total"],
        importe_medio=k["importe_medio"],
        organos_unicos=k["organos"],
        yoy_delta=yoy,
        licitaciones_30d=int(v_act),
        importe_30d=yoy_data["importe_30d"],
        por_estado=por_estado,
        por_mes=por_mes,
        top_organos=top_organos,
        funnel_estados=funnel_estados,
        hhi=adj_ind["hhi"] or 0.0,
        pct_oferta_unica=adj_ind["pct_oferta_unica"] or 0.0,
        pct_pyme=adj_ind["pct_pyme"] or 0.0,
        cobertura_oferta_unica=_cobertura(
            adj_ind.get(_K_ADJ_CON_N_OFERTAS), adj_ind.get(_K_ADJ_TOTAL)
        ),
        # OJO al destapar este: `pct_pyme` se calcula hoy con denominador
        # `COUNT(*)` —el NULL cuenta como «no PYME», ver el comentario de
        # `overview_adjudicaciones_indicadores`—, así que su valor y esta
        # cobertura hablan de bases distintas. Mientras la cobertura siga por
        # debajo del umbral el consumidor se abstiene y da igual; el día que
        # `adj_con_es_pyme` supere el 50 %, el denominador de `pct_pyme` tiene
        # que corregirse en `db/` **en el mismo cambio** o pasaremos de ocultar
        # un número dudoso a publicarlo.
        cobertura_pyme=_cobertura(adj_ind.get(_K_ADJ_CON_ES_PYME), adj_ind.get(_K_ADJ_TOTAL)),
        concentracion_top10=concentracion_top10,
        lead_time_medio=adj_ind["lead_time_medio"],
        tasa_anulacion=tasa_anulacion,
        concentracion_geo_top3=concentracion_geo_top3,
        ccaa_cubiertas=ccaa_cubiertas,
        calientes_hoy=para_hoy["calientes_hoy"],
        vencen_48h=para_hoy["vencen_48h"],
        nuevas_24h=para_hoy["nuevas_24h"],
    )
    log.info("analytics_overview_done", total=result.total_licitaciones)
    return result
