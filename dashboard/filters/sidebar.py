"""Renderiza los filtros del sidebar y devuelve un FiltersState."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import streamlit as st

from dashboard.components.icons import icon
from dashboard.components.search import render_search_autocomplete
from dashboard.filters.apply import apply_filters
from dashboard.filters.state import FiltersState
from dashboard.session_keys import (
    FILTER_KEYS,
    FS_COMPARAR,
    FS_ESTADOS,
    FS_IMP_MIN,
    FS_Q,
    FS_RANGO,
    QP_LOADED,
    RECENT_SEARCHES,
)

# Claves de session_state que el botón "Limpiar filtros" debe resetear.
_FILTER_STATE_KEYS = FILTER_KEYS

# Máximo de búsquedas recientes a recordar
_MAX_RECENT_SEARCHES = 5


def _group_header(label: str, icon_name: str) -> None:
    """Cabecera estilizada para agrupar bloques de filtros en el sidebar."""
    st.markdown(
        f'<div class="filter-group-header">{icon(icon_name, 12)} {label}</div>',
        unsafe_allow_html=True,
    )


def _clear_filters() -> None:
    """Resetea las claves de filtros del session_state."""
    for key in _FILTER_STATE_KEYS:
        if key in st.session_state:
            del st.session_state[key]
    st.session_state[QP_LOADED] = False  # forzar relectura desde URL vacía


def _set_preset_activas_sap(fmin: date, fmax: date) -> None:
    """Preset: licitaciones SAP activas en los últimos 30 días."""
    today = min(datetime.now(UTC).date(), fmax)
    st.session_state[FS_RANGO] = (max(today - timedelta(days=30), fmin), today)
    st.session_state[FS_ESTADOS] = ["Publicada"]


def _set_preset_alto_importe(fmin: date, fmax: date) -> None:
    """Preset: licitaciones con importe > 100.000 € en los últimos 90 días."""
    today = min(datetime.now(UTC).date(), fmax)
    st.session_state[FS_RANGO] = (max(today - timedelta(days=90), fmin), today)
    st.session_state[FS_IMP_MIN] = 100_000


def _set_preset_nuevas_semana(fmin: date, fmax: date) -> None:
    """Preset: nuevas licitaciones en los últimos 7 días."""
    _set_rango_preset(7, fmin, fmax)


def _set_rango_preset(n_days: int, fmin: date, fmax: date) -> None:
    """Callback para botones de rango rápido — escribe en fs_rango."""
    today = min(datetime.now(UTC).date(), fmax)
    from_date = max(today - timedelta(days=n_days), fmin)
    st.session_state[FS_RANGO] = (from_date, today)


def _set_rango_ytd(fmin: date, fmax: date) -> None:
    """Callback para botón YTD — desde el 1 de enero del año actual."""
    today = min(datetime.now(UTC).date(), fmax)
    from_date = max(date(today.year, 1, 1), fmin)
    st.session_state[FS_RANGO] = (from_date, today)


def render_sidebar_filters(df_full: pd.DataFrame) -> FiltersState:
    """Dibuja los controles de filtro en el sidebar activo y devuelve el estado."""
    _group_header("Buscar", "search")

    # ── Historial de búsquedas recientes ────────────────────────────
    _recent = st.session_state.get(RECENT_SEARCHES, [])
    if _recent:
        st.markdown(
            '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px">',
            unsafe_allow_html=True,
        )
        for _rs in _recent:
            if st.button(
                f"↩ {_rs[:20]}",
                key=f"recent_q_{_rs[:20]}",
                help=f"Repetir búsqueda: {_rs}",
            ):
                st.session_state[FS_Q] = _rs
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    q = st.text_input(
        "Buscar",
        "",
        key="fs_q",
        placeholder="Título, descripción, CPV…",
        label_visibility="collapsed",
    )

    # Autocompletado JS: sugerencias de CPV + palabras clave frecuentes
    _ac_suggestions: list[str] = []
    if "cpv_desc" in df_full.columns:
        _ac_suggestions += df_full["cpv_desc"].dropna().astype(str).unique().tolist()
    if "tipo_proyecto" in df_full.columns:
        _ac_suggestions += df_full["tipo_proyecto"].dropna().astype(str).unique().tolist()
    render_search_autocomplete(_ac_suggestions)

    # Guardar en historial si es una búsqueda nueva
    if q and q.strip():
        _recent_list: list[str] = st.session_state.get(RECENT_SEARCHES, [])
        if q not in _recent_list:
            _recent_list = [q] + [r for r in _recent_list if r != q]
            st.session_state[RECENT_SEARCHES] = _recent_list[:_MAX_RECENT_SEARCHES]

    fmin = df_full["fecha_publicacion"].min()
    fmax = df_full["fecha_publicacion"].max()
    if pd.notna(fmin) and pd.notna(fmax):
        _group_header("Periodo", "calendar")

        # ── Botones de rango rápido ──────────────────────────────────────
        fmin_d, fmax_d = fmin.date(), fmax.date()
        c7, c30, c90, cytd = st.columns(4)
        c7.button(
            "7d",
            on_click=_set_rango_preset,
            args=(7, fmin_d, fmax_d),
            use_container_width=True,
            key="fs_preset_7d",
            help="Últimos 7 días",
        )
        c30.button(
            "30d",
            on_click=_set_rango_preset,
            args=(30, fmin_d, fmax_d),
            use_container_width=True,
            key="fs_preset_30d",
            help="Últimos 30 días",
        )
        c90.button(
            "90d",
            on_click=_set_rango_preset,
            args=(90, fmin_d, fmax_d),
            use_container_width=True,
            key="fs_preset_90d",
            help="Últimos 90 días",
        )
        cytd.button(
            "YTD",
            on_click=_set_rango_ytd,
            args=(fmin_d, fmax_d),
            use_container_width=True,
            key="fs_preset_ytd",
            help="Desde el 1 de enero de este año",
        )

        rango = st.date_input(
            "Rango fechas",
            (fmin_d, fmax_d),
            min_value=fmin_d,
            max_value=fmax_d,
            key="fs_rango",
            label_visibility="collapsed",
        )
    else:
        rango = None

    _group_header("Segmentación", "filter")

    # ── Filtro de tecnología (nuevo, prominente) ─────────────────────
    tech_options = sorted(df_full["tecnologia"].dropna().unique())
    tecnologias: list[str]
    if tech_options:
        tecnologias = st.multiselect(
            "Tecnología",
            tech_options,
            key="fs_tecnologias",
        )
    else:
        tecnologias = []

    estados = st.multiselect(
        "Estado",
        sorted(df_full["estado_desc"].dropna().unique()),
        key="fs_estados",
    )
    ccaas = st.multiselect(
        "Comunidad Autónoma",
        sorted(df_full["ccaa"].dropna().unique()),
        key="fs_ccaas",
    )

    # Segmentación secundaria — colapsable para liberar espacio vertical.
    with st.expander("Más filtros", expanded=False):
        organos = st.multiselect(
            "Órgano contratante",
            sorted(df_full["organo_contratacion"].dropna().unique()),
            key="fs_organos",
        )
        tipos_proy = st.multiselect(
            "Tipo de proyecto",
            sorted(df_full["tipo_proyecto"].dropna().unique()),
            key="fs_tipos",
        )

        _group_header("Importe", "euro")
        importe_min = st.number_input(
            "Importe mínimo (€)",
            min_value=0,
            value=0,
            step=10000,
            key="fs_imp_min",
            label_visibility="collapsed",
        )

    # ── Filtros avanzados (comparativa) ────────────────────────────
    rango_b = None
    with st.expander("Filtros avanzados"):
        comparar = st.toggle("Modo comparativa", key="fs_comparar")
        if comparar and pd.notna(fmin) and pd.notna(fmax):
            st.caption("Rango B (comparar con)")
            rango_b_raw = st.date_input(
                "Rango B",
                (fmin.date(), fmax.date()),
                min_value=fmin.date(),
                max_value=fmax.date(),
                key="fs_rango_b",
                label_visibility="collapsed",
            )
            if isinstance(rango_b_raw, tuple) and len(rango_b_raw) == 2:
                rango_b = rango_b_raw

    # ── Badge de filtros activos + botón Limpiar ───────────────────
    n_active = (
        bool(q)
        + len(estados)
        + len(ccaas)
        + len(organos)
        + len(tipos_proy)
        + len(tecnologias)
        + (1 if importe_min > 0 else 0)
    )

    # ── Presets de búsquedas comunes ───────────────────────────────
    _group_header("Accesos rápidos", "zap")
    fmin_d2 = fmin.date() if pd.notna(fmin) else date.today()
    fmax_d2 = fmax.date() if pd.notna(fmax) else date.today()
    _pc1, _pc2, _pc3 = st.columns(3)
    _pc1.button(
        "Nuevas 7d",
        on_click=_set_preset_nuevas_semana,
        args=(fmin_d2, fmax_d2),
        use_container_width=True,
        key="fs_preset_nuevas7d",
        help="Licitaciones publicadas en los últimos 7 días",
    )
    _pc2.button(
        ">100K€",
        on_click=_set_preset_alto_importe,
        args=(fmin_d2, fmax_d2),
        use_container_width=True,
        key="fs_preset_alto_importe",
        help="Licitaciones con importe > 100.000 € (últimos 90 días)",
    )
    _pc3.button(
        "Activas",
        on_click=_set_preset_activas_sap,
        args=(fmin_d2, fmax_d2),
        use_container_width=True,
        key="fs_preset_activas",
        help="Licitaciones publicadas/activas en los últimos 30 días",
    )

    # ── Búsquedas guardadas ─────────────────────────────────────────
    _group_header("Búsquedas guardadas", "bookmark")
    try:
        import hashlib
        import os

        from config import settings as _settings
        from db.saved_filters import (
            delete_saved_filter,
            filters_to_json,
            json_to_session_state,
            list_saved_filters,
            save_filter,
        )

        _sf_seed = _settings.DASHBOARD_PASSWORD or os.environ.get("COMPUTERNAME", "default")
        _sf_seed_str = (
            _sf_seed.get_secret_value() if hasattr(_sf_seed, "get_secret_value") else str(_sf_seed)
        )
        _sf_user_key = hashlib.sha256(_sf_seed_str.encode()).hexdigest()[:16]
        _saved = list_saved_filters(_sf_user_key)

        # Botones para cargar cada búsqueda guardada
        for _sf in _saved:
            _sf_c1, _sf_c2 = st.columns([5, 1])
            if _sf_c1.button(
                _sf["name"][:22],
                key=f"sf_load_{_sf['id']}",
                help=f"Cargar: {_sf['name']}",
                use_container_width=True,
            ):
                for _k, _v in json_to_session_state(_sf["filters_json"]).items():
                    st.session_state[_k] = _v
                st.rerun()
            if _sf_c2.button("×", key=f"sf_del_{_sf['id']}", help="Eliminar búsqueda guardada"):
                delete_saved_filter(int(_sf["id"]))
                st.rerun()

        # Guardar búsqueda actual
        with st.expander("💾 Guardar filtros actuales", expanded=False):
            _sf_name = st.text_input(
                "Nombre",
                placeholder="Mi búsqueda",
                key="sf_new_name",
                label_visibility="collapsed",
            )
            if st.button("Guardar", key="sf_save_btn", type="primary") and _sf_name.strip():
                _cur_fs = FiltersState(
                    q=q,
                    rango=rango if isinstance(rango, tuple) and len(rango) == 2 else None,
                    estados=list(estados),
                    ccaas=list(ccaas),
                    organos=list(organos),
                    tipos_proy=list(tipos_proy),
                    tecnologias=list(tecnologias),
                    importe_min=int(importe_min),
                )
                save_filter(
                    _sf_user_key,
                    _sf_name.strip(),
                    filters_to_json(
                        _cur_fs,
                        nav_section=st.session_state.get("nav_section"),
                        detalle_cols=st.session_state.get("detalle_cols"),
                    ),
                )
                st.rerun()
    except Exception:
        pass  # No romper el sidebar si la DB no tiene la tabla aún

    # ── Contador de resultados en tiempo real ──────────────────────
    _partial_state = FiltersState(
        q=q,
        rango=rango if isinstance(rango, tuple) and len(rango) == 2 else None,
        estados=list(estados),
        ccaas=list(ccaas),
        organos=list(organos),
        tipos_proy=list(tipos_proy),
        tecnologias=list(tecnologias),
        importe_min=int(importe_min),
    )
    _n_results = len(apply_filters(df_full, _partial_state))
    _result_color = (
        "var(--color-success,#86BC24)" if _n_results > 0 else "var(--color-danger,#E21836)"
    )
    st.markdown(
        f'<p style="font-size:0.75rem;color:{_result_color};'
        f'margin:4px 0 2px 0;font-weight:600;text-align:center;">'
        f"↳ {_n_results:,} licitaci{'ones' if _n_results != 1 else 'ón'}"
        f"</p>",
        unsafe_allow_html=True,
    )

    if n_active:
        st.markdown(
            f'<p style="font-size:0.75rem;color:var(--color-accent-primary,#00A3E0);'
            f'margin:4px 0 2px 0;font-weight:600;">'
            f"&#x2022; {n_active} filtro{'s' if n_active != 1 else ''} activo{'s' if n_active != 1 else ''}"
            f"</p>",
            unsafe_allow_html=True,
        )
    st.button(
        "Limpiar filtros",
        on_click=_clear_filters,
        use_container_width=True,
        key="fs_clear",
        help="Resetea todos los filtros a sus valores por defecto.",
    )

    return FiltersState(
        q=q,
        rango=rango if isinstance(rango, tuple) and len(rango) == 2 else None,
        estados=list(estados),
        ccaas=list(ccaas),
        organos=list(organos),
        tipos_proy=list(tipos_proy),
        tecnologias=list(tecnologias),
        importe_min=int(importe_min),
        comparar=st.session_state.get(FS_COMPARAR, False),
        rango_b=rango_b,
    )
