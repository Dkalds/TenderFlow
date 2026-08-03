"""Resumen analytics — novedades, hoy, timeline, sankey, top licitaciones.

``novedades``/``hoy``/``timeline`` — los tres endpoints que alimentan la
pantalla de Resumen — agregan en Postgres vía ``db.repositories.aggregates``.
Antes materializaban la tabla ``licitaciones`` completa en pandas
(``load_stats_base_df``), que en el proceso web de Render devuelve un
DataFrame vacío desde que existe ``render_api_full_table_loads_blocked``
(ver ``services/_data_cache.py``): los tres respondían 200 con el payload a
cero y la pantalla salía en blanco, sin error que lo delatara.

``sankey`` y ``top`` siguen en pandas y por tanto siguen vacíos en Render.
No los consume ninguna pantalla del frontend (solo existen en el router y en
el cliente generado), así que se migrarán cuando vuelvan a tener consumidor.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from observability.logging import get_logger
from services.adjudicaciones import load_raw_adjudicaciones
from services.licitaciones import load_stats_base_df

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


class ResumenHoyFilters(BaseModel):
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None


class ResumenHoyResult(BaseModel):
    calientes: int = 0
    vencen_48h: int = 0
    nuevas_24h: int = 0
    total_activas: int = 0


class TimelineScatterFilters(BaseModel):
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None


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


def _load_df() -> pd.DataFrame:
    df = load_stats_base_df()
    if not df.empty and "fecha_limite" in df.columns:
        # Usa assign() en vez de asignación in-place: load_stats_base_df()
        # devuelve el DataFrame cacheado compartido (sin .copy()), así que
        # mutar una columna aquí contaminaría la caché entre requests
        # concurrentes.
        df = df.assign(
            fecha_limite_dt=pd.to_datetime(
                df["fecha_limite"],
                errors="coerce",
                utc=True,
            )
        )
    return df


def _to_repo_filters(filters: Any) -> LicitacionesFilters:
    """Traduce los filtros del endpoint (fecha_desde/hasta, ccaa, tecnologia).

    Los tres DTOs de filtros de este módulo comparten esos cuatro campos; el
    resto de campos de :class:`LicitacionesFilters` no los expone ningún
    endpoint de resumen.
    """
    fecha_desde = getattr(filters, "fecha_desde", None)
    fecha_hasta = getattr(filters, "fecha_hasta", None)
    return LicitacionesFilters(
        ccaa=getattr(filters, "ccaa", None),
        tecnologia=getattr(filters, "tecnologia", None),
        fecha_desde=fecha_desde.isoformat() if fecha_desde else None,
        fecha_hasta=fecha_hasta.isoformat() if fecha_hasta else None,
    )


def _apply_filters(df: pd.DataFrame, filters: Any) -> pd.DataFrame:
    if df.empty:
        return df
    if getattr(filters, "fecha_desde", None) is not None:
        ts = pd.Timestamp(filters.fecha_desde, tz="UTC")
        df = df[df["fecha_publicacion"] >= ts]
    if getattr(filters, "fecha_hasta", None) is not None:
        ts = pd.Timestamp(filters.fecha_hasta, tz="UTC")
        df = df[df["fecha_publicacion"] <= ts]
    if getattr(filters, "ccaa", None):
        df = df[df["ccaa"] == filters.ccaa]
    if getattr(filters, "tecnologia", None):
        df = df[df["tecnologia"] == filters.tecnologia]
    return df


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

    count, rows = _repo.resumen_novedades(desde_iso=ts.isoformat(), sample_limit=_NOVEDADES_SAMPLE)
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
    return ResumenNovedadesResult(count=count, sample=sample)


def get_resumen_hoy(filters: ResumenHoyFilters) -> ResumenHoyResult:
    """Para hoy — calientes, vencen 48h, nuevas 24h, total activas."""
    log.info("analytics_resumen_hoy_start", filters=filters.model_dump(exclude_none=True))

    hoy = datetime.now(UTC)
    counts = _repo.overview_para_hoy(
        _to_repo_filters(filters),
        hoy_iso=hoy.isoformat(),
        limite_48h_iso=(hoy + timedelta(hours=48)).isoformat(),
        hace_24h_iso=(hoy - timedelta(hours=24)).isoformat(),
    )

    result = ResumenHoyResult(
        calientes=counts["calientes_hoy"],
        vencen_48h=counts["vencen_48h"],
        nuevas_24h=counts["nuevas_24h"],
        total_activas=counts["total_activas"],
    )
    log.info("analytics_resumen_hoy_done")
    return result


def get_timeline_scatter(filters: TimelineScatterFilters) -> TimelineScatterResult:
    """Scatter data for all licitaciones (max 1000)."""
    log.info("analytics_timeline_scatter_start")

    rows = _repo.resumen_timeline_items(_to_repo_filters(filters), limit=_TIMELINE_LIMIT)
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

    log.info("analytics_timeline_scatter_done", count=len(items))
    return TimelineScatterResult(items=items)


def get_sankey_flow(filters: SankeyFilters) -> SankeyResult:
    """Sankey: tipo_contrato → estado transitions."""
    log.info("analytics_sankey_start")
    df = _load_df()
    df = _apply_filters(df, filters)

    if df.empty:
        return SankeyResult()

    if "tipo_contrato" not in df.columns or "estado" not in df.columns:
        return SankeyResult()

    work = df.dropna(subset=["tipo_contrato", "estado"])
    if work.empty:
        return SankeyResult()

    counts = work.groupby(["tipo_contrato", "estado"]).size().reset_index(name="value")

    # Build unique nodes
    tipos = sorted(work["tipo_contrato"].unique())
    estados = sorted(work["estado"].unique())
    nodes: list[SankeyNode] = []
    for t in tipos:
        nodes.append(SankeyNode(id=f"tipo_{t}", label=t))
    for e in estados:
        nodes.append(SankeyNode(id=f"estado_{e}", label=e))

    links = [
        SankeyLink(
            source=f"tipo_{row['tipo_contrato']}",
            target=f"estado_{row['estado']}",
            value=int(row["value"]),
        )
        for _, row in counts.iterrows()
    ]

    log.info("analytics_sankey_done", nodes=len(nodes), links=len(links))
    return SankeyResult(nodes=nodes, links=links)


def get_top_licitaciones(filters: TopLicitacionesFilters) -> TopLicitacionesResult:
    """Top N licitaciones by importe, enriched with adjudicatario info."""
    log.info("analytics_top_licitaciones_start", n=filters.n)
    df = _load_df()
    df = _apply_filters(df, filters)

    if df.empty:
        return TopLicitacionesResult()

    top = df.dropna(subset=["importe"]).nlargest(filters.n, "importe")

    # Load adjudicaciones for enrichment
    adj_rows = load_raw_adjudicaciones()
    adj_df = pd.DataFrame(adj_rows)

    adj_map: dict[str, tuple[str | None, float | None]] = {}
    if not adj_df.empty and "id_externo" in adj_df.columns:
        adj_name_col = "nombre" if "nombre" in adj_df.columns else "adjudicatario"
        if adj_name_col in adj_df.columns:
            for id_ext, grp in adj_df.groupby("id_externo"):
                nombre = (
                    grp[adj_name_col].dropna().iloc[0]
                    if not grp[adj_name_col].dropna().empty
                    else None
                )
                baja = None
                if "importe_adjudicado" in grp.columns and "importe_licitacion" in grp.columns:
                    imp_adj = pd.to_numeric(grp["importe_adjudicado"], errors="coerce").sum()
                    imp_lic = pd.to_numeric(grp["importe_licitacion"], errors="coerce").sum()
                    if imp_lic > 0 and pd.notna(imp_adj):
                        baja = float((1 - imp_adj / imp_lic) * 100)
                adj_map[str(id_ext)] = (str(nombre) if nombre else None, baja)

    items = []
    for _, row in top.iterrows():
        id_ext = str(row.get("id_externo", ""))
        adj_info = adj_map.get(id_ext, (None, None))
        items.append(
            TopLicitacionItem(
                id_externo=id_ext,
                titulo=row.get("titulo") if pd.notna(row.get("titulo")) else None,
                organo_contratacion=(
                    row.get("organo_contratacion")
                    if pd.notna(row.get("organo_contratacion"))
                    else None
                ),
                importe=float(row["importe"]) if pd.notna(row.get("importe")) else None,
                estado=row.get("estado") if pd.notna(row.get("estado")) else None,
                adjudicatario=adj_info[0],
                baja_pct=adj_info[1],
            )
        )

    log.info("analytics_top_licitaciones_done", count=len(items))
    return TopLicitacionesResult(items=items)
