"""Competitor analytics — market share, HHI, bidder rankings."""

from __future__ import annotations

from datetime import date

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.adjudicaciones import load_raw_adjudicaciones
from services.normalization import normalize_company, normalize_nif

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class CompetitorFilters(BaseModel):
    """Query filters for competitor analysis."""

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None
    estado: str | None = None
    importe_min: float | None = None
    limit: int = 20


class CompetitorEntry(BaseModel):
    """Single competitor entry."""

    nombre: str
    count: int
    importe: float
    cuota: float
    empresa_id: int | None = None
    nif: str | None = None
    empresa_ids: list[int] = Field(default_factory=list)
    nifs: list[str] = Field(default_factory=list)
    nombres_variantes: list[str] = Field(default_factory=list)
    es_agrupacion: bool = False
    contratos_por_anio: float = 0.0
    importe_medio: float = 0.0
    baja_media: float | None = None
    n_organos: int = 0
    ofertas_medias: float | None = None
    pct_monopolio: float | None = None
    pct_top_organo: float = 0.0
    ultima: str | None = None


class ScatterPoint(BaseModel):
    """Scatter data point for competitors."""

    nombre: str
    ticket_medio: float
    n_organos: int


class HeatmapCcaaCell(BaseModel):
    """Heatmap cell: empresa x CCAA."""

    ccaa: str
    empresa: str
    count: int


class EstacionalidadEntry(BaseModel):
    """Monthly seasonality entry."""

    mes: int
    count: int
    importe: float


class CompetitorResult(BaseModel):
    """Combined competitor response."""

    competitors: list[CompetitorEntry] = Field(default_factory=list)
    hhi: float = 0.0
    pct_oferta_unica: float = 0.0
    total_adjudicaciones: int = 0
    total_empresas: int = 0
    importe_total: float = 0.0
    scatter_data: list[ScatterPoint] = Field(default_factory=list)
    heatmap_ccaa: list[HeatmapCcaaCell] = Field(default_factory=list)
    pct_pyme: float = 0.0
    estacionalidad: list[EstacionalidadEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_GROUP_KEY = "_competitor_key"
_INVALID_NIF_KEYS = frozenset(
    {"N/A", "NA", "NULL", "NONE", "NOCONSTA", "SINCIF", "DESCONOCIDO", "000000000"}
)

# Curated fallback while the ``grupos_empresariales`` master is populated.
# Only verified tax IDs are grouped: a shared word in a company name is not a
# sufficiently safe signal for joining distinct legal entities.
_CURATED_GROUPS_BY_NIF: dict[str, tuple[str, str]] = {
    "B81690471": ("deloitte", "Deloitte"),  # Deloitte Consulting, S.L.U.
    "B16436099": ("deloitte", "Deloitte"),  # Deloitte Technology & Transformation, S.L.U.
    "B86466448": ("deloitte", "Deloitte"),  # Deloitte Advisory, S.L.
}


def _clean_text(values: pd.Series) -> pd.Series:
    """Return trimmed nullable strings, treating blanks as missing."""
    cleaned = values.astype("string").str.strip()
    return cleaned.mask(cleaned.eq(""))


def _optional_text_column(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(pd.NA, index=df.index, dtype="string")
    return _clean_text(df[column])


def _normalise_identity_text(values: pd.Series, *, nif: bool = False) -> pd.Series:
    normalizer = normalize_nif if nif else normalize_company
    normalised = values.map(
        lambda value: normalizer(str(value)) if pd.notna(value) else None,
    ).astype("string")
    if nif:
        normalised = normalised.mask(normalised.isin(_INVALID_NIF_KEYS))
    return normalised


def _corporate_group_identity(
    df: pd.DataFrame,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return master/curated group keys and the preferred display name.

    The company master is authoritative. The small tax-ID map above only fills
    gaps while those same relationships are absent from the master.
    """
    master_ids = pd.to_numeric(
        df.get(
            "empresa_grupo_id",
            pd.Series(pd.NA, index=df.index, dtype="Int64"),
        ),
        errors="coerce",
    ).astype("Int64")
    master_names = _optional_text_column(df, "empresa_grupo_master")

    curated = df["_nif_key"].map(_CURATED_GROUPS_BY_NIF)
    curated_keys = curated.map(
        lambda value: value[0] if isinstance(value, tuple) else None,
    ).astype("string")
    curated_names = curated.map(
        lambda value: value[1] if isinstance(value, tuple) else None,
    ).astype("string")

    master_keys = master_ids.map(
        lambda value: f"master:{int(value)}" if pd.notna(value) else None,
    ).astype("string")
    curated_keys = curated_keys.map(
        lambda value: f"curated:{value}" if pd.notna(value) else None,
    ).astype("string")
    group_names = master_names.combine_first(curated_names)
    return master_keys, curated_keys, group_names


def _connected_identity_keys(df: pd.DataFrame) -> list[str]:
    """Build transitive identity groups from master id, NIF and normalised name.

    A disjoint-set is intentional here: two rows may be connected by a NIF while
    another alias connects them by name. Iterating the three compact identity
    columns with ``itertuples`` avoids the much slower ``iterrows`` hot path.
    """
    parent: dict[str, str] = {}

    def find(token: str) -> str:
        parent.setdefault(token, token)
        root = token
        while parent[root] != root:
            root = parent[root]
        while parent[token] != token:
            next_token = parent[token]
            parent[token] = root
            token = next_token
        return root

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    primary_tokens: list[str] = []
    identity_columns = df[
        [
            "_master_group_key",
            "_curated_group_key",
            "_empresa_id_key",
            "_nif_key",
            "_name_key",
        ]
    ]
    for position, (master_group, curated_group, empresa_id, nif_key, name_key) in enumerate(
        identity_columns.itertuples(index=False, name=None)
    ):
        tokens: list[str] = []
        for group_key in (master_group, curated_group):
            if pd.notna(group_key):
                tokens.append(f"grupo:{group_key}")
        if pd.notna(empresa_id):
            tokens.append(f"empresa:{int(empresa_id)}")
        if pd.notna(nif_key):
            tokens.append(f"nif:{nif_key}")
        if pd.notna(name_key):
            tokens.append(f"nombre:{name_key}")
        if not tokens:
            tokens.append(f"fila:{position}")
        primary = tokens[0]
        find(primary)
        for token in tokens[1:]:
            union(primary, token)
        primary_tokens.append(primary)

    return [find(token) for token in primary_tokens]


def _preferred_names(df: pd.DataFrame) -> dict[str, str]:
    """Choose a stable display name, preferring master names over raw aliases."""
    candidates = pd.concat(
        [
            df[[_GROUP_KEY, "_corporate_group_name"]]
            .rename(columns={"_corporate_group_name": "candidate"})
            .assign(priority=0),
            df[[_GROUP_KEY, "_master_name"]]
            .rename(columns={"_master_name": "candidate"})
            .assign(priority=1),
            df[[_GROUP_KEY, "_raw_name"]]
            .rename(columns={"_raw_name": "candidate"})
            .assign(priority=2),
        ],
        ignore_index=True,
    ).dropna(subset=["candidate"])
    if candidates.empty:
        return {}
    ranked = (
        candidates.groupby([_GROUP_KEY, "priority", "candidate"], sort=False, observed=True)
        .size()
        .rename("frequency")
        .reset_index()
        .sort_values(
            [_GROUP_KEY, "priority", "frequency", "candidate"],
            ascending=[True, True, False, True],
        )
        .drop_duplicates(subset=[_GROUP_KEY])
    )
    return dict(ranked[[_GROUP_KEY, "candidate"]].itertuples(index=False, name=None))


def _unique_strings(values: pd.Series) -> list[str]:
    return sorted({str(value) for value in values.dropna() if str(value).strip()})


def _unique_ints(values: pd.Series) -> list[int]:
    return sorted({int(value) for value in values.dropna()})


def _prepare_company_identity(df: pd.DataFrame) -> pd.DataFrame:
    """Attach one traceable competitor identity to every award row.

    Matching signals are exact after normalisation: canonical ``empresa_id``,
    NIF/CIF, or company name. This intentionally groups equal names with
    different NIFs for market analysis, without mutating the conservative
    company master or pretending that an ambiguous group has one profile id.
    """
    prepared = df.copy()
    raw_column = "adjudicatario" if "adjudicatario" in prepared.columns else "nombre"
    prepared["_raw_name"] = _optional_text_column(prepared, raw_column)
    prepared["_master_name"] = _optional_text_column(prepared, "empresa_nombre_master")
    effective_name = prepared["_master_name"].combine_first(prepared["_raw_name"])
    prepared["_name_key"] = _normalise_identity_text(effective_name)

    prepared["_raw_nif"] = _optional_text_column(prepared, "nif")
    prepared["_master_nif"] = _optional_text_column(prepared, "empresa_nif_master")
    effective_nif = prepared["_master_nif"].combine_first(prepared["_raw_nif"])
    prepared["_nif_key"] = _normalise_identity_text(effective_nif, nif=True)
    (
        prepared["_master_group_key"],
        prepared["_curated_group_key"],
        prepared["_corporate_group_name"],
    ) = _corporate_group_identity(prepared)

    empresa_id_values = (
        prepared["empresa_id"]
        if "empresa_id" in prepared.columns
        else pd.Series(pd.NA, index=prepared.index, dtype="Int64")
    )
    prepared["_empresa_id_key"] = pd.to_numeric(
        empresa_id_values,
        errors="coerce",
    ).astype("Int64")
    prepared[_GROUP_KEY] = pd.Categorical(_connected_identity_keys(prepared))

    name_map = _preferred_names(prepared)
    prepared["empresa"] = (
        prepared[_GROUP_KEY].astype("string").map(name_map).fillna("Empresa sin identificar")
    )
    return prepared.drop(
        columns=[
            "_master_name",
            "_raw_nif",
            "_name_key",
            "_master_group_key",
            "_curated_group_key",
            "_corporate_group_name",
        ]
    )


def _identity_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Return traceability metadata once per analytical competitor group."""
    summary = (
        df.groupby(_GROUP_KEY, sort=False, observed=True)
        .agg(
            empresa_ids=("_empresa_id_key", _unique_ints),
            nifs=("_nif_key", _unique_strings),
            nombres_variantes=("_raw_name", _unique_strings),
            master_nifs=("_master_nif", _unique_strings),
        )
        .reset_index()
    )
    summary["empresa_id"] = summary["empresa_ids"].map(
        lambda values: values[0] if len(values) == 1 else None
    )
    single_nif = summary["nifs"].str.len().eq(1)
    preferred_nif = summary["master_nifs"].str[0].fillna(summary["nifs"].str[0])
    summary["nif"] = preferred_nif.where(single_nif)
    summary["es_agrupacion"] = (
        summary["empresa_ids"].str.len().gt(1)
        | summary["nifs"].str.len().gt(1)
        | summary["nombres_variantes"].str.len().gt(1)
    )
    return summary.drop(columns=["master_nifs"])


def _load_df(ccaa: str | None) -> pd.DataFrame:
    ccaa_filter = (ccaa,) if ccaa else None
    rows = load_raw_adjudicaciones(ccaa_filter=ccaa_filter)
    df = pd.DataFrame(rows)
    if not df.empty:
        if "fecha_adjudicacion" in df.columns:
            df["fecha_adjudicacion"] = pd.to_datetime(
                df["fecha_adjudicacion"],
                errors="coerce",
                utc=True,
            )
        df["importe"] = pd.to_numeric(
            df.get(
                "importe_adjudicado",
                df.get("importe_adjudicacion", df.get("importe", pd.Series(dtype=float))),
            ),
            errors="coerce",
        )
        # Una sola clave analítica combina maestro, CIF y nombre normalizados.
        df = _prepare_company_identity(df)
    return df


def _apply_filters(df: pd.DataFrame, filters: CompetitorFilters) -> pd.DataFrame:
    if df.empty:
        return df
    if filters.fecha_desde is not None and "fecha_adjudicacion" in df.columns:
        ts = pd.Timestamp(filters.fecha_desde, tz="UTC")
        df = df[df["fecha_adjudicacion"] >= ts]
    if filters.fecha_hasta is not None and "fecha_adjudicacion" in df.columns:
        ts = pd.Timestamp(filters.fecha_hasta, tz="UTC")
        df = df[df["fecha_adjudicacion"] <= ts]
    # Eje de producto: segmentación por tecnología (SAP, Salesforce, …).
    if filters.tecnologia and "tecnologia" in df.columns:
        df = df[df["tecnologia"] == filters.tecnologia]
    if filters.estado and "estado" in df.columns:
        df = df[df["estado"] == filters.estado]
    if filters.importe_min is not None and "importe_licitacion" in df.columns:
        imp = pd.to_numeric(df["importe_licitacion"], errors="coerce")
        df = df[imp >= filters.importe_min]
    return df


def _compute_hhi(shares: pd.Series) -> float:
    """Herfindahl-Hirschman Index from market share percentages (0-10000)."""
    return float((shares**2).sum())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_competitors(filters: CompetitorFilters) -> CompetitorResult:
    """Compute competitor rankings, HHI, and single-bid percentage."""
    log.info("analytics_competitors_start", filters=filters.model_dump(exclude_none=True))
    df = _load_df(filters.ccaa)
    df = _apply_filters(df, filters)

    if df.empty or "empresa" not in df.columns:
        log.info("analytics_competitors_done", total=0)
        return CompetitorResult()

    total = len(df)

    identity_by_group = _identity_summary(df).set_index(_GROUP_KEY).to_dict(orient="index")
    g = (
        df.groupby(_GROUP_KEY, sort=False, observed=True)
        .agg(
            empresa=("empresa", "first"),
            count=(_GROUP_KEY, "count"),
            importe=("importe", "sum"),
        )
        .sort_values(["count", "importe"], ascending=False)
        .reset_index()
    )

    total_importe = float(g["importe"].sum(skipna=True)) or 1.0
    g["cuota"] = g["importe"] / total_importe * 100

    # Compute extra fields
    active_years_by_empresa: dict[str, int] = {}
    if "fecha_adjudicacion" in df.columns:
        dated = df.dropna(subset=["fecha_adjudicacion"]).copy()
        if not dated.empty:
            dated["_activity_year"] = dated["fecha_adjudicacion"].dt.year
            active_years_by_empresa = {
                str(key): max(int(value), 1)
                for key, value in dated.groupby(_GROUP_KEY, observed=True)["_activity_year"]
                .nunique()
                .items()
            }

    # baja_media per empresa
    baja_by_empresa: dict[str, float] = {}
    if "importe_adjudicado" in df.columns and "importe_licitacion" in df.columns:
        adj_col = df.get("importe_adjudicado")
        lic_col = df.get("importe_licitacion")
        if adj_col is not None and lic_col is not None:
            imp_adj = pd.to_numeric(adj_col, errors="coerce")
            imp_lic = pd.to_numeric(lic_col, errors="coerce")
            df_baja = df.copy()
            df_baja["_baja"] = ((1 - imp_adj / imp_lic) * 100).where(
                (imp_lic > 0) & imp_adj.notna()
            )
            baja_means = df_baja.groupby(_GROUP_KEY, observed=True)["_baja"].mean()
            baja_by_empresa = {str(k): float(v) for k, v in baja_means.items() if pd.notna(v)}

    # n_organos per empresa
    n_organos_map: dict[str, int] = {}
    if "organo_contratacion" in df.columns:
        n_organos_map = {
            str(k): int(v)
            for k, v in df.groupby(_GROUP_KEY, observed=True)["organo_contratacion"]
            .nunique()
            .items()
        }

    # ofertas_medias per empresa
    ofertas_map: dict[str, float] = {}
    if "n_ofertas_recibidas" in df.columns:
        _ofertas = pd.to_numeric(df["n_ofertas_recibidas"], errors="coerce")
        _df_of = df.assign(_ofertas=_ofertas)
        ofertas_map = {
            str(k): float(v)
            for k, v in _df_of.groupby(_GROUP_KEY, observed=True)["_ofertas"].mean().items()
            if pd.notna(v)
        }

    # Señal de "oferta única" basada en el número REAL de ofertantes
    # (``n_ofertas_recibidas``), no en el nº de adjudicatarios: la tabla
    # ``adjudicaciones`` solo contiene ganadores, así que contar adjudicatarios
    # distintos por licitación da ~1 siempre y no mide competencia. Solo se
    # consideran licitaciones que reportan el dato (cobertura parcial según fuente).
    lic_id_col = "id_externo" if "id_externo" in df.columns else "licitacion_id"
    single_bid_lics: set[object] = set()
    lics_con_ofertas: set[object] = set()
    if lic_id_col in df.columns and "n_ofertas_recibidas" in df.columns:
        _ofertas_lic = pd.to_numeric(df["n_ofertas_recibidas"], errors="coerce")
        _per_lic = df.assign(_ofertas=_ofertas_lic).dropna(subset=["_ofertas"])
        ofertas_por_lic = _per_lic.groupby(lic_id_col)["_ofertas"].max()
        lics_con_ofertas = set(ofertas_por_lic.index)
        single_bid_lics = set(ofertas_por_lic[ofertas_por_lic <= 1].index)

    # pct_monopolio per empresa (% de sus licitaciones —con dato— sin rival)
    pct_monopolio_map: dict[str, float | None] = {}
    if lic_id_col in df.columns and lics_con_ofertas:
        covered = df[df[lic_id_col].isin(lics_con_ofertas)]
        covered_counts = covered.groupby(_GROUP_KEY, observed=True)[lic_id_col].nunique()
        single_counts = (
            covered[covered[lic_id_col].isin(single_bid_lics)]
            .groupby(_GROUP_KEY, observed=True)[lic_id_col]
            .nunique()
            .reindex(covered_counts.index, fill_value=0)
        )
        pct_monopolio_map = {
            str(key): float(value) for key, value in (single_counts / covered_counts * 100).items()
        }

    # pct_top_organo per empresa (% from their most common organo)
    pct_top_organo_map: dict[str, float] = {}
    if "organo_contratacion" in df.columns:
        organ_rows = df.dropna(subset=["organo_contratacion"])
        organ_counts = organ_rows.groupby([_GROUP_KEY, "organo_contratacion"], observed=True).size()
        if not organ_counts.empty:
            top_organ = organ_counts.groupby(level=0, observed=True).max()
            group_sizes = df.groupby(_GROUP_KEY, observed=True).size()
            pct_top_organo_map = {
                str(key): float(value)
                for key, value in (top_organ / group_sizes * 100).dropna().items()
            }

    # ultima adjudicacion per empresa
    ultima_map: dict[str, str] = {}
    if "fecha_adjudicacion" in df.columns:
        last_dates = df.groupby(_GROUP_KEY, observed=True)["fecha_adjudicacion"].max().dropna()
        ultima_map = {
            str(key): str(value.strftime("%Y-%m-%d")) for key, value in last_dates.items()
        }

    entries: list[CompetitorEntry] = []
    entry_columns = g.head(filters.limit)[[_GROUP_KEY, "empresa", "count", "importe", "cuota"]]
    for group_key, empresa, count, importe, cuota in entry_columns.itertuples(
        index=False, name=None
    ):
        key = str(group_key)
        identity = identity_by_group.get(key, {})
        representative_id = identity.get("empresa_id")
        representative_nif = identity.get("nif")
        entries.append(
            CompetitorEntry(
                nombre=str(empresa),
                count=int(count),
                importe=float(importe or 0),
                cuota=float(cuota),
                empresa_id=(int(representative_id) if pd.notna(representative_id) else None),
                nif=str(representative_nif) if pd.notna(representative_nif) else None,
                empresa_ids=list(identity.get("empresa_ids", [])),
                nifs=list(identity.get("nifs", [])),
                nombres_variantes=list(identity.get("nombres_variantes", [])),
                es_agrupacion=bool(identity.get("es_agrupacion", False)),
                contratos_por_anio=float(count) / active_years_by_empresa.get(key, 1),
                importe_medio=float(importe or 0) / max(int(count), 1),
                baja_media=baja_by_empresa.get(key),
                n_organos=int(n_organos_map.get(key, 0)),
                ofertas_medias=ofertas_map.get(key),
                pct_monopolio=pct_monopolio_map.get(key),
                pct_top_organo=pct_top_organo_map.get(key, 0.0),
                ultima=ultima_map.get(key),
            )
        )

    hhi = _compute_hhi(g["cuota"])

    # % de licitaciones con un solo ofertante (sobre las que reportan
    # ``n_ofertas_recibidas``). Bandera roja clásica de contratación pública.
    total_lics = len(lics_con_ofertas)
    pct_unica = (len(single_bid_lics) / total_lics * 100) if total_lics else 0.0

    # Scatter data: ticket_medio vs n_organos
    scatter_data = [
        ScatterPoint(
            nombre=str(empresa),
            ticket_medio=float(importe or 0) / max(int(count), 1),
            n_organos=int(n_organos_map.get(str(group_key), 1)),
        )
        for group_key, empresa, count, importe in g.head(filters.limit)[
            [_GROUP_KEY, "empresa", "count", "importe"]
        ].itertuples(index=False, name=None)
    ]

    # Desglose CCAA x empresa para las empresas listadas (``filters.limit``).
    # El heatmap del front muestra su propio top 10, pero el drill-down de
    # cualquier competidor de la tabla necesita su desglose: limitar a 10 aquí
    # dejaba vacío el panel de detalle para las posiciones 11..N.
    heatmap_ccaa: list[HeatmapCcaaCell] = []
    if "ccaa" in df.columns:
        listed_groups = g.head(filters.limit)[_GROUP_KEY]
        hm_df = df[df[_GROUP_KEY].isin(listed_groups)]
        hm_counts = (
            hm_df.groupby(["ccaa", _GROUP_KEY], observed=True)
            .agg(empresa=("empresa", "first"), count=(_GROUP_KEY, "count"))
            .reset_index()
        )
        heatmap_ccaa = [
            HeatmapCcaaCell(ccaa=str(ccaa), empresa=str(empresa), count=int(count))
            for ccaa, empresa, count in hm_counts[["ccaa", "empresa", "count"]].itertuples(
                index=False, name=None
            )
        ]

    # pct_pyme
    pct_pyme = 0.0
    if "es_pyme" in df.columns:
        pyme_vals = pd.to_numeric(df["es_pyme"], errors="coerce").fillna(0)
        pct_pyme = float(pyme_vals.astype(bool).sum() / len(df) * 100) if len(df) > 0 else 0.0

    # estacionalidad mensual
    estacionalidad: list[EstacionalidadEntry] = []
    if "fecha_adjudicacion" in df.columns:
        monthly = df.dropna(subset=["fecha_adjudicacion"]).copy()
        if not monthly.empty:
            monthly["_mes"] = monthly["fecha_adjudicacion"].dt.month
            agg_m = (
                monthly.groupby("_mes")
                .agg(_count=(_GROUP_KEY, "count"), _importe=("importe", "sum"))
                .reset_index()
            )
            estacionalidad = [
                EstacionalidadEntry(
                    mes=int(month),
                    count=int(count),
                    importe=float(importe or 0),
                )
                for month, count, importe in agg_m[["_mes", "_count", "_importe"]].itertuples(
                    index=False, name=None
                )
            ]

    result = CompetitorResult(
        competitors=entries,
        hhi=hhi,
        pct_oferta_unica=pct_unica,
        total_adjudicaciones=total,
        total_empresas=len(g),
        importe_total=total_importe,
        scatter_data=scatter_data,
        heatmap_ccaa=heatmap_ccaa,
        pct_pyme=pct_pyme,
        estacionalidad=estacionalidad,
    )
    log.info("analytics_competitors_done", total=total, hhi=hhi)
    return result
