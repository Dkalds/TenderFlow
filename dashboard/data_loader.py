"""Carga y enriquecimiento de datos desde SQLite, con caché Streamlit."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd
import streamlit as st

from config import settings
from dashboard.classifiers import (
    cpv_label,
    detect_modules,
    detect_project_type,
    estado_label,
    tipo_contrato_label,
)
from dashboard.normalize import normalize_company, normalize_nif
from dashboard.utils.dates import month_start
from db.database import connect, init_db
from observability.logging import get_logger
from observability.histograms import timed_query
from shared.geo import nuts_to_ccaa

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
    init_db()
    with connect() as c:
        # Columnas de resumen: excluye blobs grandes (descripcion, raw_keywords)
        # para reducir I/O y memoria en el dashboard. Las páginas de detalle
        # usan _load_detail() que sí selecciona todos los campos.
        sql = (
            "SELECT id_externo, titulo, organo_contratacion, importe, estado, "
            "fecha_publicacion, ccaa, nuts_code, cpv, url, tecnologia, "
            "tipo_contrato, moneda, provincia, duracion_valor, duracion_unidad, "
            "fecha_limite, fecha_inicio, fecha_fin, fecha_extraccion "
            "FROM licitaciones "
            "WHERE tecnologia IS NOT NULL AND tecnologia != '' "
            "ORDER BY fecha_publicacion DESC"
        )
        params: tuple[Any, ...] = ()
        if limit is not None and limit > 0:
            sql += " LIMIT ?"
            params = (int(limit),)
        with timed_query("load_licitaciones"):
            cursor = c.execute(sql, params)
            df = _rows_to_df(cursor)
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

    desc_col = df["descripcion"].fillna("") if "descripcion" in df.columns else ""
    text_blob = df["titulo"].fillna("") + " " + desc_col

    _safe_apply(
        df, "modulos", detect_modules, source=text_blob, fallback=[], op_name="detect_modules"
    )
    try:
        df["modulos_str"] = df["modulos"].apply(
            lambda mods: ", ".join(mods) if isinstance(mods, list) else ""
        )
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
    _safe_apply(
        df, "estado_desc", estado_label, source=df["estado"], fallback="", op_name="estado_label"
    )
    _safe_apply(
        df,
        "tipo_contrato_desc",
        tipo_contrato_label,
        source=df["tipo_contrato"],
        fallback="",
        op_name="tipo_contrato_label",
    )

    _backfill_ccaa(df)

    for col in ("estado", "tipo_contrato", "ccaa"):
        if col in df.columns:
            df[col] = df[col].astype("category")

    return df


@st.cache_resource(ttl=settings.DASHBOARD_CACHE_TTL or None)
def _load_dataframe_shared(limit: int | None = None) -> pd.DataFrame:
    """Carga base compartida entre todas las sesiones (no copiar).

    Orquesta ``_load_raw()`` + ``_enrich_dataframe()``.  Al usar
    ``@st.cache_resource`` el resultado se reutiliza entre reruns y sesiones;
    ``load_dataframe`` hace ``.copy()`` antes de entregarlo a cada sesión.

    Args:
        limit: Si se proporciona, limita el número de filas leídas de la DB
               (útil en sesiones con datasets grandes para acelerar primera carga).
               ``None`` (default) carga el dataset completo.
    """
    df = _load_raw(limit).copy()  # copy: no mutar el objeto cacheado de _load_raw
    return _enrich_dataframe(df)


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
    return _load_dataframe_shared(limit).copy()  # .copy() necesario: cache_resource comparte objeto


@st.cache_data(ttl=settings.DASHBOARD_CACHE_TTL or None, show_spinner="Cargando adjudicaciones…")
def load_adjudicaciones(limit: int | None = None) -> pd.DataFrame:
    """Carga adjudicaciones enriquecidas desde la DB.

    Args:
        limit: Límite opcional de filas en la query SQL.
    """
    with connect() as c:
        sql = (
            "SELECT a.*, l.titulo, l.organo_contratacion, l.url AS url_lic, "
            "       l.fecha_publicacion, l.descripcion AS descripcion_lic, "
            "       l.importe AS importe_licitacion "
            "FROM adjudicaciones a "
            "LEFT JOIN licitaciones l ON l.id_externo = a.licitacion_id "
            "ORDER BY a.fecha_adjudicacion DESC"
        )
        params: tuple[Any, ...] = ()
        if limit is not None and limit > 0:
            sql += " LIMIT ?"
            params = (int(limit),)
        cursor = c.execute(sql, params)
        df = _rows_to_df(cursor)
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
    return df


def _build_canonical_names(df: pd.DataFrame) -> pd.Series:
    """Calcula el nombre canónico (más frecuente) por ``empresa_key``.

    Extraído como función separada para facilitar caché y testabilidad.
    Si falla, devuelve ``df['nombre']`` sin canonicalizar (degradación graciosa).
    """
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


@st.cache_data(ttl=settings.DASHBOARD_CACHE_TTL or None)
def load_extracciones() -> pd.DataFrame:
    with connect() as c:
        cursor = c.execute("SELECT * FROM extracciones ORDER BY fecha DESC")
        df = _rows_to_df(cursor)
    if not df.empty:
        df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    return df


def invalidate_caches() -> None:
    """Fuerza recarga de todas las fuentes cacheadas en la próxima llamada."""
    _load_raw.clear()
    _load_dataframe_shared.clear()
    load_adjudicaciones.clear()
    load_extracciones.clear()
    # Limpiar también caches de KPI bar
    try:
        from dashboard.kpi_bar import _compute_kpis_cached, _last_12m_series

        _compute_kpis_cached.clear()
        _last_12m_series.clear()
    except Exception:
        log.debug("kpi_cache_clear_failed")
