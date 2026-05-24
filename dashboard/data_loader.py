"""Carga y enriquecimiento de datos desde SQLite, con caché Streamlit."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd
import streamlit as st

from config import settings
from dashboard.classifiers import (
    ESTADO_LABELS,
    TIPO_CONTRATO_LABELS,
    cpv_label,
    detect_modules,
    detect_project_type,
)
from dashboard.normalize import normalize_company, normalize_nif
from dashboard.utils.dates import month_start
from observability.logging import get_logger
from shared.geo import nuts_to_ccaa
from shared.schemas import validate_adjudicaciones, validate_licitaciones

log = get_logger(__name__)


def _rows_to_df(cursor: Any) -> pd.DataFrame:
    """Convierte el resultado de un cursor a DataFrame usando cursor.description.

    Centraliza el patrón repetido ``cols = [d[0] for d in cursor.description]``
    + ``pd.DataFrame(rows, columns=cols)`` en un único helper reutilizable.
    """
    rows = cursor.fetchall()
    cols = [d[0] for d in cursor.description]
    return pd.DataFrame(rows, columns=cols)


def _backfill_ccaa(df: pd.DataFrame, log_suffix: str = "") -> None:
    """Rellena la columna ``ccaa`` desde ``nuts_code`` donde está vacía.

    Operación in-place. Si alguna de las columnas no existe o la conversión
    falla, loguea un warning y continúa sin modificar el DataFrame.
    """
    if "ccaa" not in df.columns or "nuts_code" not in df.columns:
        return
    try:
        mask = df["ccaa"].isna() & df["nuts_code"].notna()
        df.loc[mask, "ccaa"] = df.loc[mask, "nuts_code"].apply(nuts_to_ccaa)
    except Exception as e:
        col_label = f"ccaa_{log_suffix}" if log_suffix else "ccaa"
        log.warning("data_loader_enrichment_failed", column=col_label, error=str(e))


def _safe_apply(
    df: pd.DataFrame,
    column: str,
    fn: Callable[[Any], Any],
    *,
    source: pd.Series | None = None,
    fallback: Any = None,
    op_name: str = "",
) -> None:
    """Aplica ``fn`` a ``source`` (o ``df[column]``) con fallback en caso de error.

    Si ``fn`` falla globalmente (e.g. dependencia rota), rellena toda la columna
    con ``fallback`` y loguea, en vez de hacer caer la carga completa.
    """
    src = source if source is not None else df[column]
    try:
        df[column] = src.apply(fn)
    except Exception as e:
        log.warning(
            "data_loader_enrichment_failed",
            column=column,
            op=op_name or fn.__name__,
            error=str(e),
        )
        df[column] = fallback


@st.cache_resource(ttl=settings.DASHBOARD_CACHE_TTL or None)
def _load_raw(limit: int | None = None) -> pd.DataFrame:
    """Query SQL + conversiones de tipo básicas — sin enriquecimiento.

    Cacheada por separado para que ``invalidate_caches`` pueda limpiar también
    la capa raw y para facilitar tests unitarios del enriquecimiento.
    """
    from services.licitaciones import load_raw as svc_load_raw

    rows = svc_load_raw(limit=limit)
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["fecha_publicacion"] = pd.to_datetime(
        df["fecha_publicacion"],
        errors="coerce",
        format="mixed",
        utc=True,
    )
    df["importe"] = pd.to_numeric(df["importe"], errors="coerce")
    df["mes"] = month_start(df["fecha_publicacion"])
    df["anyo"] = df["fecha_publicacion"].dt.year
    return df


def _enrich_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Aplica enriquecimientos NLP/lookup sobre el DataFrame raw.

    Función pura (sin estado global ni Streamlit) — facilita tests unitarios y
    permite reutilizarla fuera del contexto cacheado.

    Args:
        df: DataFrame raw procedente de ``_load_raw()`` (se modifica in-place
            y se devuelve por conveniencia).

    Returns:
        El mismo ``df`` con columnas adicionales: ``modulos``, ``modulos_str``,
        ``tipo_proyecto``, ``cpv_desc``, ``estado_desc``,
        ``tipo_contrato_desc``, y categorías de baja cardinalidad.
    """
    if df.empty:
        return df

    desc_col = (
        df["descripcion"].fillna("")
        if "descripcion" in df.columns
        else pd.Series("", index=df.index)
    )
    text_blob = df["titulo"].fillna("") + " " + desc_col

    _safe_apply(
        df, "modulos", detect_modules, source=text_blob, fallback=[], op_name="detect_modules"
    )
    try:
        df["modulos_str"] = df["modulos"].str.join(", ")
    except Exception as e:  # pragma: no cover
        log.warning("data_loader_enrichment_failed", column="modulos_str", error=str(e))
        df["modulos_str"] = ""

    _safe_apply(
        df,
        "tipo_proyecto",
        detect_project_type,
        source=text_blob,
        fallback="Otro",
        op_name="detect_project_type",
    )
    _safe_apply(df, "cpv_desc", cpv_label, source=df["cpv"], fallback="", op_name="cpv_label")

    # Vectorized estado_label — simple dict lookup, much faster than .apply()
    try:
        stripped_estado = df["estado"].str.strip()
        df["estado_desc"] = (
            stripped_estado.map(ESTADO_LABELS).fillna(stripped_estado).fillna("Desconocido")
        )
    except Exception as e:
        log.warning(
            "data_loader_enrichment_failed", column="estado_desc", op="estado_label", error=str(e)
        )
        df["estado_desc"] = ""

    # Vectorized tipo_contrato_label — simple dict lookup
    try:
        stripped_tc = df["tipo_contrato"].str.strip()
        mapped_tc = stripped_tc.map(TIPO_CONTRATO_LABELS)
        unmapped = mapped_tc.isna() & stripped_tc.notna() & (stripped_tc != "")
        mapped_tc[unmapped] = "Tipo " + stripped_tc[unmapped]
        df["tipo_contrato_desc"] = mapped_tc.fillna("—")
    except Exception as e:
        log.warning(
            "data_loader_enrichment_failed",
            column="tipo_contrato_desc",
            op="tipo_contrato_label",
            error=str(e),
        )
        df["tipo_contrato_desc"] = ""

    _backfill_ccaa(df)

    for col in ("ccaa", "estado", "tipo_contrato", "provincia", "tipo_proyecto"):
        if col in df.columns:
            df[col] = df[col].astype("category")

    return df


@st.cache_data(ttl=settings.DASHBOARD_CACHE_TTL or None)
def _load_dataframe_shared(limit: int | None = None) -> pd.DataFrame:
    """Carga base compartida entre todas las sesiones.

    Orquesta ``_load_raw()`` + ``_enrich_dataframe()``.  Al usar
    ``@st.cache_data`` el resultado se copia automáticamente entre reruns
    y sesiones, por lo que no se necesita ``.copy()`` adicional.

    Args:
        limit: Si se proporciona, limita el número de filas leídas de la DB
               (útil en sesiones con datasets grandes para acelerar primera carga).
               ``None`` (default) carga el dataset completo.
    """
    df = _load_raw(limit).copy()  # copy: no mutar el objeto cacheado de _load_raw
    df = _enrich_dataframe(df)
    try:
        validate_licitaciones(df, lazy=True)
    except Exception as _e:
        log.warning("data_loader_schema_violation", error=str(_e))
    return df


def load_dataframe(limit: int | None = None) -> pd.DataFrame:
    """Devuelve una copia del DataFrame base (segura para mutaciones por sesión).

    Aplica un rate limit defensivo (60 llamadas/min) para detectar sesiones
    que recargan en bucle. Si se excede, se sirve igualmente la copia cacheada
    pero se loguea el evento.

    Si detecta que el scraper ha ingestado datos nuevos (señal de archivo),
    invalida la caché antes de servir los datos.

    Args:
        limit: Límite opcional de filas (forwarded a ``_load_dataframe_shared``).
    """
    # Comprobar si el scraper ha señalizado datos nuevos
    try:
        import streamlit as _st

        from shared.cache_signal import check_cache_signal

        _last_check_key = "_cache_signal_last_check"
        last_check: float = _st.session_state.get(_last_check_key, 0.0)
        if check_cache_signal(last_check):
            invalidate_caches()
            _st.session_state[_last_check_key] = __import__("time").time()
            log.debug("data_loader_cache_invalidated_by_signal")
        elif last_check == 0.0:
            # Primera carga de la sesión: registrar el timestamp actual
            _st.session_state[_last_check_key] = __import__("time").time()
    except Exception:
        log.debug("cache_signal_check_unavailable")

    # Best-effort: si no hay contexto Streamlit (tests, scripts), saltarse el throttle.
    try:
        from dashboard.utils.rate_limit import check_rate_limit

        check_rate_limit("load_dataframe", max_calls=60, window_seconds=60.0)
    except Exception:
        log.debug("rate_limit_check_unavailable")
    return _load_dataframe_shared(limit)  # @st.cache_data ya devuelve una copia por sesión


@st.cache_data(
    ttl=settings.DASHBOARD_CACHE_TTL or None,
    show_spinner="Cargando adjudicaciones…",
    persist="disk",
)
def load_adjudicaciones(
    limit: int | None = None,
    ccaa_filter: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Carga adjudicaciones enriquecidas desde la DB.

    Args:
        limit: Límite opcional de filas en la query SQL.
        ccaa_filter: Si se proporciona, push-down de ``WHERE a.ccaa IN (...)`` a SQL.
    """
    from services.adjudicaciones import load_raw_adjudicaciones

    rows = load_raw_adjudicaciones(limit=limit, ccaa_filter=ccaa_filter)
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["fecha_adjudicacion"] = pd.to_datetime(df["fecha_adjudicacion"], errors="coerce")
    df["fecha_publicacion"] = pd.to_datetime(
        df["fecha_publicacion"],
        errors="coerce",
        format="mixed",
        utc=True,
    )
    for col in (
        "importe_adjudicado",
        "importe_pagable",
        "oferta_minima",
        "oferta_maxima",
        "importe_licitacion",
    ):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["baja_pct"] = ((1 - df["importe_adjudicado"] / df["importe_licitacion"]) * 100).where(
        (df["importe_licitacion"] > 0) & df["importe_adjudicado"].notna()
    )

    _fp = df["fecha_publicacion"]
    if hasattr(_fp.dt, "tz") and _fp.dt.tz is not None:
        _fp = _fp.dt.tz_localize(None)
    df["lead_time_dias"] = (df["fecha_adjudicacion"] - _fp).dt.days
    df.loc[df["lead_time_dias"] <= 0, "lead_time_dias"] = pd.NA

    _backfill_ccaa(df, "adj")

    df["es_ute"] = df["nombre"].str.contains(r"\bU\.?T\.?E\.?\b", case=False, na=False, regex=True)

    _safe_apply(
        df,
        "nombre_norm",
        normalize_company,
        source=df["nombre"],
        fallback=None,
        op_name="normalize_company",
    )
    _safe_apply(
        df, "nif_norm", normalize_nif, source=df["nif"], fallback=None, op_name="normalize_nif"
    )
    df["empresa_key"] = df["nif_norm"].where(
        df["nif_norm"].notna() & (df["nif_norm"] != ""), df["nombre_norm"]
    )

    df["nombre_canonico"] = _build_canonical_names(df)
    try:
        validate_adjudicaciones(df, lazy=True)
    except Exception as _e:
        log.warning("data_loader_adj_schema_violation", error=str(_e))
    return df


def _build_canonical_names(df: pd.DataFrame) -> pd.Series:
    """Calcula el nombre canónico (más frecuente) por ``empresa_key``.

    Usa Polars para el groupby cuando está disponible (10-20× más rápido que
    ``groupby + value_counts``). Si Polars no está instalado, cae de vuelta a
    pandas. Si ambos fallan, devuelve ``df['nombre']`` sin canonicalizar.
    """
    try:
        import polars as pl

        pl_df = pl.from_pandas(df[["empresa_key", "nombre"]].dropna(subset=["empresa_key"]))
        # mode().first() = valor más frecuente
        canon_pl = pl_df.group_by("empresa_key").agg(
            pl.col("nombre").mode().first().alias("nombre_canon")
        )
        canon = dict(
            zip(canon_pl["empresa_key"].to_list(), canon_pl["nombre_canon"].to_list(), strict=False)
        )
        return df["empresa_key"].map(canon).fillna(df["nombre"])
    except ImportError:
        pass
    except Exception as e:
        log.warning("data_loader_canonical_polars_failed", error=str(e))
    # Pandas fallback
    try:
        canon = (
            df.dropna(subset=["empresa_key"])
            .groupby("empresa_key")["nombre"]
            .agg(lambda s: s.value_counts().index[0])
            .to_dict()
        )
        return df["empresa_key"].map(canon).fillna(df["nombre"])
    except Exception as e:
        log.warning("data_loader_canonical_failed", error=str(e))
        return df["nombre"]


@st.cache_data(ttl=settings.DASHBOARD_CACHE_TTL or None, persist="disk")
def load_extracciones() -> pd.DataFrame:
    from services.extraction_runs import load_extracciones as svc_load_extracciones

    rows = svc_load_extracciones()
    df = pd.DataFrame(rows)
    if not df.empty:
        df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    return df


@st.cache_data(ttl=settings.DASHBOARD_CACHE_TTL or None)
def load_mat_clusters() -> pd.DataFrame:
    """Carga los clusters pre-computados desde ``mat_clusters``.

    Returns vacío si la tabla aún no ha sido poblada por el scheduler.
    """
    from db.database import connect_read

    with connect_read() as c:
        try:
            cur = c.execute(
                "SELECT id_externo, cluster_id, cluster_label, updated_at FROM mat_clusters"
            )
            return _rows_to_df(cur)
        except Exception as exc:
            log.warning("data_loader_mat_clusters_unavailable", error=str(exc))
            return pd.DataFrame()


@st.cache_data(ttl=settings.DASHBOARD_CACHE_TTL or None)
def load_mat_top_empresas() -> pd.DataFrame:
    """Carga el ranking top-N de empresas por CCAA desde ``mat_top_empresas_ccaa``.

    Returns vacío si la tabla aún no ha sido poblada por el scheduler.
    """
    from db.database import connect_read

    with connect_read() as c:
        try:
            cur = c.execute(
                "SELECT ccaa, rank, nombre_canon, n_adj, importe_total, updated_at "
                "FROM mat_top_empresas_ccaa ORDER BY ccaa, rank"
            )
            return _rows_to_df(cur)
        except Exception as exc:
            log.warning("data_loader_mat_top_empresas_unavailable", error=str(exc))
            return pd.DataFrame()


def invalidate_caches() -> None:
    """Fuerza recarga de todas las fuentes cacheadas en la próxima llamada."""
    _load_raw.clear()
    _load_dataframe_shared.clear()
    load_adjudicaciones.clear()
    load_extracciones.clear()
    load_mat_clusters.clear()
    load_mat_top_empresas.clear()
    # Limpiar también caches de KPI bar
    try:
        from dashboard.kpi_bar import _last_12m_series, compute_kpis

        compute_kpis.clear()
        _last_12m_series.clear()
    except Exception:
        log.debug("kpi_cache_clear_failed")
