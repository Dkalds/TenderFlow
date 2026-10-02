"""Resumen analytics — novedades, hoy, timeline, sankey, top licitaciones.

Los cinco endpoints agregan en Postgres vía ``db.repositories.aggregates``
(ADR-023). Antes materializaban la tabla ``licitaciones`` completa en pandas
(``load_stats_base_df``, ya retirado), que en el proceso web de Render
devolvía un DataFrame vacío por el cortacircuitos full-table (también
retirado al completar la migración): respondían 200 con el payload a cero y
la pantalla salía en blanco, sin error que lo delatara.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from db.repositories.kpi_snapshots import read_overview_snapshot_for
from observability.logging import get_logger
from shared.dto import DESCRIPCION_GRANDES_EN_PLAZO

log = get_logger(__name__)

_repo = AggregateRepository()

# Cota de puntos del scatter de /resumen/timeline (la misma que aplicaba el
# ``head(1000)`` de pandas, ahora empujada al ``LIMIT`` de la query).
_TIMELINE_LIMIT = 1000
_NOVEDADES_SAMPLE = 10


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class ResumenNovedadesSample(BaseModel):
    id_externo: str
    titulo: str | None = None
    importe: float | None = None
    organo_contratacion: str | None = None


class ResumenNovedadesResult(BaseModel):
    count: int = 0
    sample: list[ResumenNovedadesSample] = Field(default_factory=list)
    # Corte contra el que se contó, en ISO-8601 UTC. El recuento salía sin él y
    # eso dejaba al cliente sin poder señalar *cuáles* son las nuevas: con la
    # muestra de diez podía marcar diez filas y ninguna más, así que en una
    # tabla de treinta la fila nueva número once aparecía como vieja. Marcar
    # parte de las filas es peor que no marcar ninguna, porque la ausencia de
    # marca se lee como "esta no es nueva". Publicando el corte, el cliente
    # compara `fecha_publicacion >= desde` y acierta en todas.
    # El Resumen siempre recibe uno (la última visita, o el tope de 14 días).
    # `None` solo en la ruta de la campana, que aún lee `users.last_login`, una
    # columna que no existe: el cliente entonces no marca nada, que es la
    # salida segura.
    desde: str | None = None


class AmbitoResumen(BaseModel):
    """El ámbito entero de la barra de filtros, tal como lo aplica el listado.

    ``/resumen/hoy`` y ``/resumen/timeline`` solo declaraban fecha, CCAA y
    tecnología; el resto del ámbito viajaba en la query y FastAPI lo descartaba
    sin decir nada. Con un chip de estado o una búsqueda activos, la banda de
    «Mercado abierto» y las publicaciones contaban otro universo que la tira de
    contexto de al lado, y la pantalla tenía que avisarlo panel por panel.
    """

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None
    estado: str | None = None
    q: str | None = None
    importe_min: float | None = None
    importe_max: float | None = None
    provincia: str | None = None
    procedimiento: str | None = None
    solo_abiertas: bool = False


class ResumenHoyFilters(AmbitoResumen):
    pass


class ResumenHoyResult(BaseModel):
    # OJO con el nombre: aquí "caliente" es **importe ≥ P75, abierta y en
    # plazo**, no la banda `Caliente` del score (≥75 puntos) que cuenta
    # `/analytics/pipeline`. Son dos preguntas distintas —"cuáles son gordas"
    # frente a "cuáles merecen mi tiempo"— que compartían nombre en dos
    # páginas contiguas. El campo se conserva porque es contrato público; la
    # UI ya no lo llama "Calientes".
    calientes: int = Field(default=0, description=DESCRIPCION_GRANDES_EN_PLAZO)
    vencen_48h: int = 0
    nuevas_24h: int = 0
    total_activas: int = 0
    # El corte de importe con el que se contó `calientes`, para que la tarjeta
    # que lo enseña pueda abrir su listado (`importe_min=<p75>&solo_abiertas=true`)
    # en vez de un listado más ancho que la cifra.
    #
    # Con ámbito activo es el P75 **del ámbito**: la CTE `p75` de
    # `aggregates.overview_para_hoy` lo calcula sobre el subconjunto filtrado y
    # ahora sale de la query. Antes no salía y aquí llegaba `None`, así que con
    # cualquier chip puesto —el caso normal de quien trabaja una tecnología— la
    # tarjeta abría un listado más ancho que su cifra.
    #
    # `None` solo cuando el ámbito no tiene ningún importe. El consumidor debe
    # tratarlo como "no puedo enlazar exacto", nunca como cero.
    importe_p75: float | None = None


class TimelineScatterFilters(AmbitoResumen):
    #: Reparte las filas por toda la ventana en vez de devolver las más
    #: recientes. Lo pide la nube de puntos; la tabla de «últimas
    #: publicaciones» necesita justo lo contrario y por eso es opt-in.
    muestrear: bool = False


class TimelineScatterItem(BaseModel):
    id_externo: str
    titulo: str | None = None
    importe: float | None = None
    fecha_publicacion: str | None = None
    estado: str | None = None
    organo_contratacion: str | None = None
    tipo_contrato: str | None = None
    ccaa: str | None = None


class TimelineScatterResult(BaseModel):
    items: list[TimelineScatterItem] = Field(default_factory=list)
    #: Expedientes de la ventana antes de recortar. La UI lo necesita para
    #: decir si enseña todo o una parte, en vez de callarse el tope.
    total: int = 0
    #: ``items`` es una muestra sistemática repartida por la ventana, no las
    #: filas más recientes.
    muestreado: bool = False


class SankeyNode(BaseModel):
    id: str
    label: str


class SankeyLink(BaseModel):
    source: str
    target: str
    value: int


class SankeyFilters(BaseModel):
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None


class SankeyResult(BaseModel):
    nodes: list[SankeyNode] = Field(default_factory=list)
    links: list[SankeyLink] = Field(default_factory=list)


class TopLicitacionesFilters(BaseModel):
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None
    n: int = 10


class TopLicitacionItem(BaseModel):
    id_externo: str
    titulo: str | None = None
    organo_contratacion: str | None = None
    importe: float | None = None
    estado: str | None = None
    adjudicatario: str | None = None
    baja_pct: float | None = None


class TopLicitacionesResult(BaseModel):
    items: list[TopLicitacionItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_repo_filters(filters: Any) -> LicitacionesFilters:
    """Traduce los filtros del endpoint a :class:`LicitacionesFilters`.

    Todos los DTOs de filtros de este módulo traen fecha, CCAA y tecnología;
    los de ``/resumen/hoy`` y ``/resumen/timeline`` traen además el resto del
    ámbito (:class:`AmbitoResumen`). Los deprecados (sankey, top) no, y por eso
    se lee con ``getattr``: un campo ausente es un filtro que no se aplica.
    """
    fecha_desde = getattr(filters, "fecha_desde", None)
    fecha_hasta = getattr(filters, "fecha_hasta", None)
    return LicitacionesFilters(
        ccaa=getattr(filters, "ccaa", None),
        tecnologia=getattr(filters, "tecnologia", None),
        fecha_desde=fecha_desde.isoformat() if fecha_desde else None,
        fecha_hasta=fecha_hasta.isoformat() if fecha_hasta else None,
        estado=getattr(filters, "estado", None),
        q=getattr(filters, "q", None),
        importe_min=getattr(filters, "importe_min", None),
        importe_max=getattr(filters, "importe_max", None),
        provincia=getattr(filters, "provincia", None),
        procedimiento=getattr(filters, "procedimiento", None),
        solo_abiertas=bool(getattr(filters, "solo_abiertas", False)),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_resumen_novedades(user_id: int) -> ResumenNovedadesResult:
    """New licitaciones since user's last login."""
    log.info("analytics_resumen_novedades_start", user_id=user_id)

    from db.users import get_user_by_id

    user = get_user_by_id(user_id)
    if not user:
        return ResumenNovedadesResult()

    last_login = user.get("last_login")
    if not last_login:
        return ResumenNovedadesResult()

    # ``last_login`` llega como string ISO o datetime según el driver; se
    # normaliza con la misma tolerancia que antes (valor ilegible -> sin
    # novedades, nunca una excepción) al formato ISO que espera el repository.
    ts = pd.to_datetime(last_login, errors="coerce", utc=True)
    if pd.isna(ts):
        return ResumenNovedadesResult()

    return get_resumen_novedades_desde(ts.isoformat())


def get_resumen_novedades_desde(
    desde_iso: str, filters: AmbitoResumen | None = None
) -> ResumenNovedadesResult:
    """Licitaciones publicadas desde ``desde_iso``, en el ámbito ``filters``.

    Es lo que pide el Resumen (``/analytics/resumen/novedades``), con el corte
    ya resuelto por la ruta: la última visita de ``notification_reads``, la
    misma que usa la banda «desde tu última visita»
    (:func:`services.novedades.corte_ultima_visita`). Sin ``filters``, el
    mercado entero.

    :func:`get_resumen_novedades` —por ``user_id``— lee ``users.last_login``,
    una columna que ninguna migración crea: siempre devuelve vacío. El Resumen
    dejó de usarla porque decía «Todo al día» sin haber mirado nada; la
    campana (``/notifications``) aún la llama.
    """
    log.info("analytics_resumen_novedades_desde_start")
    count, rows = _repo.resumen_novedades(
        _to_repo_filters(filters) if filters is not None else None,
        desde_iso=desde_iso,
        sample_limit=_NOVEDADES_SAMPLE,
    )
    sample = [
        ResumenNovedadesSample(
            id_externo=str(row["id_externo"]),
            titulo=row.get("titulo"),
            importe=float(row["importe"]) if row.get("importe") is not None else None,
            organo_contratacion=row.get("organo_contratacion"),
        )
        for row in rows
    ]

    log.info("analytics_resumen_novedades_done", count=count)
    return ResumenNovedadesResult(count=count, sample=sample, desde=desde_iso)


def get_resumen_hoy(filters: ResumenHoyFilters) -> ResumenHoyResult:
    """Para hoy — calientes, vencen 48h, nuevas 24h, total activas."""
    log.info("analytics_resumen_hoy_start", filters=filters.model_dump(exclude_none=True))

    hoy = datetime.now(UTC)
    repo_filters = _to_repo_filters(filters)
    # Mismo camino rápido que `/analytics/overview`: el P75 de importe y el
    # recuento de activas son globales y los deja precalculados el pipeline de
    # ingesta, así que sin filtros esta consulta deja de recorrer la tabla
    # entera. Sin snapshot (o con filtros) se calcula en vivo como antes. Con un
    # filtro de solo una tecnología frecuente llega su variante precalculada,
    # pero esa no trae P75 ni activas (son globales): valen `None` y se calculan
    # en vivo igual que con cualquier otro filtro.
    snap = read_overview_snapshot_for(repo_filters)
    counts = _repo.overview_para_hoy(
        repo_filters,
        hoy_iso=hoy.isoformat(),
        limite_48h_iso=(hoy + timedelta(hours=48)).isoformat(),
        hace_24h_iso=(hoy - timedelta(hours=24)).isoformat(),
        p75=snap.importe_p75 if snap is not None else None,
        total_activas=snap.total_activas if snap is not None else None,
    )

    result = ResumenHoyResult(
        calientes=counts["calientes_hoy"],
        vencen_48h=counts["vencen_48h"],
        nuevas_24h=counts["nuevas_24h"],
        total_activas=counts["total_activas"],
        # El umbral que usó el contador de arriba, venga del snapshot (tabla
        # entera) o de la CTE del ámbito filtrado.
        importe_p75=counts["importe_p75"],
    )
    log.info("analytics_resumen_hoy_done")
    return result


def get_timeline_scatter(filters: TimelineScatterFilters) -> TimelineScatterResult:
    """Hasta ``_TIMELINE_LIMIT`` publicaciones de la ventana, con su total.

    Con ``muestrear`` la selección se reparte por todo el rango pedido en vez
    de quedarse en las más recientes — ver ``resumen_timeline_items``.
    """
    log.info("analytics_timeline_scatter_start", muestrear=filters.muestrear)

    rows, total = _repo.resumen_timeline_items(
        _to_repo_filters(filters), limit=_TIMELINE_LIMIT, muestrear=filters.muestrear
    )
    items = [
        TimelineScatterItem(
            id_externo=str(row["id_externo"]),
            titulo=row.get("titulo"),
            importe=float(row["importe"]) if row.get("importe") is not None else None,
            fecha_publicacion=row.get("fecha_publicacion"),
            estado=row.get("estado"),
            organo_contratacion=row.get("organo_contratacion"),
            tipo_contrato=row.get("tipo_contrato"),
            ccaa=row.get("ccaa"),
        )
        for row in rows
    ]

    log.info("analytics_timeline_scatter_done", count=len(items), total=total)
    return TimelineScatterResult(
        items=items,
        total=total,
        # Sólo es muestra si de verdad se dejó algo fuera: con la ventana
        # entera dentro del tope, el modo no cambia lo que se devuelve.
        muestreado=filters.muestrear and total > len(items),
    )


def get_sankey_flow(filters: SankeyFilters) -> SankeyResult:
    """Sankey: tipo_contrato → estado transitions (GROUP BY en Postgres)."""
    log.info("analytics_sankey_start")
    counts = _repo.resumen_sankey(_to_repo_filters(filters))
    if not counts:
        return SankeyResult()

    tipos = sorted({str(r["tipo_contrato"]) for r in counts})
    estados = sorted({str(r["estado"]) for r in counts})
    nodes: list[SankeyNode] = [SankeyNode(id=f"tipo_{t}", label=t) for t in tipos]
    nodes.extend(SankeyNode(id=f"estado_{e}", label=e) for e in estados)

    links = [
        SankeyLink(
            source=f"tipo_{r['tipo_contrato']}",
            target=f"estado_{r['estado']}",
            value=int(r["value"]),
        )
        for r in counts
    ]

    log.info("analytics_sankey_done", nodes=len(nodes), links=len(links))
    return SankeyResult(nodes=nodes, links=links)


def get_top_licitaciones(filters: TopLicitacionesFilters) -> TopLicitacionesResult:
    """Top N licitaciones by importe (ORDER BY … LIMIT en Postgres).

    La baja replica la fórmula del pandas original, que comparaba la suma de
    ``importe_adjudicado`` del grupo contra la suma de la columna
    ``importe_licitacion`` del join (``n_adj * importe`` de la licitación).
    """
    log.info("analytics_top_licitaciones_start", n=filters.n)
    rows = _repo.resumen_top_licitaciones(_to_repo_filters(filters), n=filters.n)

    items = []
    for r in rows:
        baja: float | None = None
        n_adj = int(r.get("n_adj") or 0)
        importe = r.get("importe")
        if n_adj > 0 and importe:
            # Baja agregada del expediente: todo lo adjudicado (suma de sus lotes)
            # contra el presupuesto ÚNICO del expediente. El denominador era
            # ``n_adj * importe`` — replicaba el bug del pandas original que sumaba
            # ``importe_licitacion`` del join (una copia de ``l.importe`` por fila),
            # inflando el divisor n veces: con 4 lotes adjudicados al completo daba
            # ~75% de baja en vez de ~0%. Para n_adj=1 el valor no cambia.
            imp_lic = float(importe)
            sum_adj = float(r.get("sum_adj") or 0.0)
            if imp_lic > 0:
                baja = float((1 - sum_adj / imp_lic) * 100)
        items.append(
            TopLicitacionItem(
                id_externo=str(r["id_externo"]),
                titulo=r.get("titulo"),
                organo_contratacion=r.get("organo_contratacion"),
                importe=float(importe) if importe is not None else None,
                estado=r.get("estado"),
                adjudicatario=r.get("adjudicatario"),
                baja_pct=baja,
            )
        )

    log.info("analytics_top_licitaciones_done", count=len(items))
    return TopLicitacionesResult(items=items)
