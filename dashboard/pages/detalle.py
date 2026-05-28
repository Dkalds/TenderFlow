"""Página Detalle — tabla completa y vista expandida."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pandas as pd
import streamlit as st

from dashboard.components.cards import status_badge
from dashboard.components.preview import licitacion_popover
from dashboard.components.states import guarded_render
from dashboard.components.tables import data_table
from dashboard.components.timeline import timeline_popover
from dashboard.components.toasts import notify_error, notify_success
from dashboard.data_loader import load_adjudicaciones
from dashboard.kpi_config import SCORING_BAND_LEVELS
from dashboard.pages._base import PageContext
from dashboard.session_keys import COMPARE_IDS, LIC_FOCUS
from dashboard.stats import risk_flags, score_oportunidad
from dashboard.utils.export import to_csv_bytes, to_excel_bytes
from dashboard.utils.format import fmt_eur, highlight_match
from dashboard.utils.pagination import paginated_df, reset_pagination
from db.notifications import mark_all_read as _mark_all_read
from db.notifications import mark_read as _mark_read_notification
from observability.logging import get_logger

log = get_logger(__name__)

# Columnas disponibles en el selector (label → columna interna)
_AVAILABLE_COLS: dict[str, str] = {
    "Nuevo": "_nuevo",
    "Score": "score",
    "Banda": "banda",
    "Fecha": "fecha_publicacion",
    "Título": "titulo",
    "Órgano": "organo_contratacion",
    "CCAA": "ccaa",
    "Importe": "importe",
    "Moneda": "moneda",
    "Estado": "estado_desc",
    "Tipo proyecto": "tipo_proyecto",
    "Módulos": "modulos_str",
    "CPV": "cpv_desc",
    "Riesgo": "riesgo_flags",
    "Enlace": "url",
}
_DEFAULT_COLS = [
    "Nuevo",
    "Score",
    "Banda",
    "Fecha",
    "Título",
    "Órgano",
    "CCAA",
    "Importe",
    "Estado",
    "Tipo proyecto",
    "Módulos",
    "CPV",
    "Riesgo",
    "Enlace",
]


@guarded_render
def render(ctx: PageContext) -> None:
    df = ctx.df

    # ── Flags de riesgo + score ──────────────────────────────────────────────
    # Calculados sobre df_full para tener contexto histórico completo (CPV P10, monopolio…)
    _scoring_failed: list[str] = []
    try:
        adj_rf = load_adjudicaciones()
        rf = risk_flags(ctx.df_full, adj_rf)
        df = df.merge(
            rf[["id_externo", "riesgo_flags", "riesgo_score"]], on="id_externo", how="left"
        )
        df["riesgo_flags"] = df["riesgo_flags"].fillna("")
        df["riesgo_score"] = df["riesgo_score"].fillna(0).astype(int)
    except Exception as e:
        log.warning("detalle_risk_flags_failed", error=str(e), exc_info=True)
        _scoring_failed.append("risk_flags")
        df = df.copy()
        df["riesgo_flags"] = ""
        df["riesgo_score"] = 0

    try:
        sc = score_oportunidad(ctx.df_full, adj_rf)
        df = df.merge(sc[["id_externo", "score", "banda", "desglose"]], on="id_externo", how="left")
        df["score"] = df["score"].fillna(0).astype(int)
        df["banda"] = df["banda"].fillna("—")
    except Exception as e:
        log.warning("detalle_score_oportunidad_failed", error=str(e), exc_info=True)
        _scoring_failed.append("score_oportunidad")
        df = df.copy() if "score" not in df.columns else df
        df["score"] = 0
        df["banda"] = "—"
        df["desglose"] = pd.Series([{} for _ in range(len(df))], index=df.index, dtype=object)

    if _scoring_failed:
        st.warning(
            f"⚠️ Scoring no disponible ({', '.join(_scoring_failed)}) — mostrando datos sin ponderación.",
            icon="⚠️",
        )

    st.subheader(f"Detalle de licitaciones ({len(df)})")
    # Indicador de ranking FTS5
    if getattr(ctx.df, "attrs", {}).get("fts_ranked"):
        st.caption(
            "🔎 Resultados ordenados por relevancia · "
            "Plataforma de Contratación del Sector Público — reutilización al amparo de la Ley 37/2007"
        )
    else:
        st.caption(
            "Plataforma de Contratación del Sector Público — reutilización al amparo de la Ley 37/2007"
        )

    # ── M10: Indicador visto/no visto ─────────────────────────────────────
    _unread_ids: set[str] = set()
    import hashlib
    import os

    from config import settings as _cfg

    _seed_v = _cfg.DASHBOARD_PASSWORD.get_secret_value() or os.environ.get(
        "COMPUTERNAME", "default"
    )
    _ukey_v = hashlib.sha256(_seed_v.encode()).hexdigest()[:16]
    try:
        from db.notifications import get_unread_ids

        _all_ids = df["id_externo"].dropna().astype(str).tolist()
        _unread_ids = set(get_unread_ids(_ukey_v, _all_ids))
    except sqlite3.OperationalError as _e:
        log.debug("detalle_unread_ids_unavailable", error=str(_e))  # tabla no existe aún

    # Añadir indicador visual al DataFrame
    if _unread_ids:
        df = df.copy()
        df["_nuevo"] = df["id_externo"].apply(lambda x: "🔵" if str(x) in _unread_ids else "")

    # ── Selector de columnas ──────────────────────────────────────────────
    _sel_cols = st.multiselect(
        "Columnas visibles",
        options=list(_AVAILABLE_COLS.keys()),
        default=st.session_state.get("detalle_cols", _DEFAULT_COLS),
        key="detalle_cols",
        help="Personaliza qué columnas se muestran en la tabla.",
    )
    # Mapear a columnas internas disponibles en df
    cols = [_AVAILABLE_COLS[c] for c in _sel_cols if _AVAILABLE_COLS[c] in df.columns]
    if not cols:
        cols = [c for c in _AVAILABLE_COLS.values() if c in df.columns]

    # ── Botones de exportación ────────────────────────────────────────────
    _ts = datetime.now(UTC).strftime("%Y%m%d_%H%M")
    cdl1, cdl2 = st.columns([1, 6])
    with cdl1:
        st.download_button(
            "⬇️ Excel",
            data=to_excel_bytes(df),
            file_name=f"licitaciones_{_ts}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with cdl2:
        st.download_button(
            "⬇️ CSV",
            data=to_csv_bytes(df),
            file_name=f"licitaciones_{_ts}.csv",
            mime="text/csv",
        )

    # cols ya viene definido por el selector de columnas arriba
    cols = [c for c in cols if c in df.columns]
    show = df[cols].sort_values("score", ascending=False) if "score" in cols else df[cols]

    # ── Paginación server-side — envía al navegador solo la página activa ──
    # Resetear a página 1 cuando cambian los filtros (cambio de tamaño del df)
    _pg_key = "detalle_table"
    _prev_len_key = "_detalle_prev_len"
    if st.session_state.get(_prev_len_key) != len(show):
        reset_pagination(_pg_key)
        st.session_state[_prev_len_key] = len(show)

    show_page, _ = paginated_df(show, page_size=100, key=_pg_key)

    event = data_table(
        show_page,
        height=600,
        key="detalle_table",
        selection_mode="multi-row",
        column_config={
            "score": st.column_config.ProgressColumn(
                "Score", format="%d", min_value=0, max_value=100, width="small"
            ),
            "banda": st.column_config.TextColumn("Banda", width="small"),
            "fecha_publicacion": st.column_config.DatetimeColumn("Fecha", format="DD-MM-YYYY"),
            "titulo": st.column_config.TextColumn("Título", width="large"),
            "organo_contratacion": st.column_config.TextColumn("Órgano", width="medium"),
            "ccaa": st.column_config.TextColumn("CCAA", width="small"),
            "importe": st.column_config.NumberColumn("Importe", format="%.0f €"),
            "estado_desc": st.column_config.TextColumn("Estado"),
            "tipo_proyecto": st.column_config.TextColumn("Tipo"),
            "modulos_str": st.column_config.TextColumn("Módulos"),
            "cpv_desc": st.column_config.TextColumn("CPV"),
            "riesgo_flags": st.column_config.TextColumn("⚠️ Riesgo", width="medium"),
            "url": st.column_config.LinkColumn("Enlace", display_text="🔗"),
        },
    )

    # ── M1+M6: Bulk action bar ────────────────────────────────────────────
    _selected_rows: list[int] = []
    if event is not None:
        sel = getattr(event, "selection", None)
        if sel is not None:
            _selected_rows = (
                sel.get("rows", []) if isinstance(sel, dict) else getattr(sel, "rows", [])
            )
    if _selected_rows:
        _sel_df = show.iloc[_selected_rows]
        st.info(f"**{len(_selected_rows)}** licitaciones seleccionadas")
        _ba1, _ba2, _ba3, _ba4 = st.columns(4)
        with _ba1:
            if st.button(
                "⬇️ Exportar selección (Excel)", key="bulk_export", use_container_width=True
            ):
                _ts_bulk = datetime.now(UTC).strftime("%Y%m%d_%H%M")
                st.download_button(
                    "Descargar",
                    data=to_excel_bytes(_sel_df),
                    file_name=f"seleccion_{_ts_bulk}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="bulk_dl",
                )
        with _ba2:
            if st.button("🔄 Comparar (primeras 2)", key="bulk_compare", use_container_width=True):
                # Get id_externo from the original df using the selected indices
                _orig_indices = show.index[_selected_rows[:2]]
                _cmp_list = df.loc[_orig_indices, "id_externo"].astype(str).tolist()
                st.session_state[COMPARE_IDS] = _cmp_list[:2]
                st.rerun()
        with _ba3:
            if st.button("⭐ Seguir todos (watchlist)", key="bulk_watch", use_container_width=True):
                try:
                    from dashboard.auth import get_current_user
                    from db.watchlist import WatchlistEntry, add_entry

                    _user = get_current_user()
                    _uid = _user.get("user_id") if _user else None
                    _added = 0
                    _orig_sel = df.loc[show.index[_selected_rows]]
                    for _sr in _orig_sel.itertuples(index=False):
                        _cpv_r = str(
                            getattr(_sr, "cpv", None) or getattr(_sr, "cpv_desc", None) or ""
                        )
                        _cpv_p = _cpv_r[:8].strip()
                        if _cpv_p:
                            add_entry(
                                WatchlistEntry(
                                    user_key=_ukey_v,
                                    cpv_prefix=_cpv_p,
                                    keyword=str(getattr(_sr, "titulo", ""))[:60] or None,
                                    ccaa=getattr(_sr, "ccaa", None) or None,
                                    user_id=_uid,
                                )
                            )
                            _added += 1
                    notify_success(f"{_added} CPVs añadidos a tu watchlist.")
                except Exception as exc:
                    notify_error(f"Error al añadir a watchlist: {exc}")
        with _ba4:
            if st.button("✅ Marcar como leídas", key="bulk_read", use_container_width=True):
                try:
                    _orig_sel_r = df.loc[show.index[_selected_rows]]
                    _ids_to_mark = _orig_sel_r["id_externo"].dropna().astype(str).tolist()
                    _mark_all_read(_ukey_v, _ids_to_mark)  # una sola transacción executemany
                    notify_success("Marcadas como leídas.")
                except Exception as exc:
                    notify_error(f"Error: {exc}")

    st.divider()
    # ── Vista expandida paginada ──────────────────────────────────────────
    _DETALLE_PAGE_SIZE = 10
    _df_sorted = df.sort_values("score", ascending=False)
    _total_det = len(_df_sorted)
    _det_pages = max(1, (_total_det + _DETALLE_PAGE_SIZE - 1) // _DETALLE_PAGE_SIZE)
    _det_page_key = "detalle_expand_page"
    # ── M4: Deep-link auto-expand — navigate to page containing target row ──
    _lic_focus = st.session_state.pop(LIC_FOCUS, None)
    if _lic_focus:
        _focus_idx = _df_sorted.index[_df_sorted["id_externo"] == _lic_focus]
        if len(_focus_idx):
            _pos = _df_sorted.index.get_loc(_focus_idx[0])
            if isinstance(_pos, int):
                st.session_state[_det_page_key] = _pos // _DETALLE_PAGE_SIZE
    if _det_page_key not in st.session_state:
        st.session_state[_det_page_key] = 0
    _det_cur = min(st.session_state[_det_page_key], _det_pages - 1)
    _det_start = _det_cur * _DETALLE_PAGE_SIZE

    # ── Comparación lado a lado (M5 enhanced) ──────────────────────────────
    _compare_ids: list[str] = st.session_state.get(COMPARE_IDS, [])
    if len(_compare_ids) == 2:
        _cmp_rows = [
            _df_sorted[_df_sorted["id_externo"] == _cid].iloc[0]
            for _cid in _compare_ids
            if not _df_sorted[_df_sorted["id_externo"] == _cid].empty
        ]
        if len(_cmp_rows) == 2:
            with st.expander("🔄 Comparación seleccionada", expanded=True):
                _a, _b = _cmp_rows
                # ── KPI deltas row ────────────────────────────────────
                _kc1, _kc2, _kc3 = st.columns(3)
                _score_a = int(_a.get("score") or 0)
                _score_b = int(_b.get("score") or 0)
                _imp_a = float(_a.get("importe") or 0)
                _imp_b = float(_b.get("importe") or 0)
                with _kc1:
                    st.metric("Score A↔B", f"{_score_a} vs {_score_b}", delta=_score_b - _score_a)
                with _kc2:
                    _imp_delta = _imp_b - _imp_a
                    st.metric(
                        "Importe A↔B",
                        f"{fmt_eur(_imp_a)} vs {fmt_eur(_imp_b)}",
                        delta=f"{'+' if _imp_delta >= 0 else ''}{fmt_eur(_imp_delta)}",
                        delta_color="off",
                    )
                with _kc3:
                    st.metric("Banda", f"{_a.get('banda', '—')} vs {_b.get('banda', '—')}")

                # ── Field-by-field comparison table ───────────────────
                _CMP_FIELDS = [
                    ("Título", "titulo"),
                    ("Órgano", "organo_contratacion"),
                    ("Estado", "estado_desc"),
                    ("Tipo proyecto", "tipo_proyecto"),
                    ("Módulos SAP", "modulos_str"),
                    ("CPV", "cpv_desc"),
                    ("CCAA", "ccaa"),
                    ("Riesgo", "riesgo_flags"),
                ]
                _cmp_cols = st.columns(2)
                for _ci, _crow in enumerate([_a, _b]):
                    with _cmp_cols[_ci]:
                        st.markdown(f"**{str(_crow.get('titulo', '—'))[:60]}**")
                        for _lbl, _col in _CMP_FIELDS:
                            if _col == "titulo":
                                continue
                            _val = str(_crow.get(_col, "—") or "—")
                            _other = str(([_a, _b][1 - _ci]).get(_col, "—") or "—")
                            _diff_style = "🟢" if _val == _other else "🔴"
                            st.markdown(f"{_diff_style} **{_lbl}:** {_val}")

                if st.button("Limpiar comparación", key="cmp_clear"):
                    st.session_state[COMPARE_IDS] = []
                    st.rerun()

    st.subheader(
        f"Vista expandida — página {_det_cur + 1}/{_det_pages} "
        f"({_DETALLE_PAGE_SIZE} por página, {_total_det} total)"
    )
    _q = ctx.filters.q if ctx.filters.q and ctx.filters.q.strip() else ""
    for _, row in _df_sorted.iloc[_det_start : _det_start + _DETALLE_PAGE_SIZE].iterrows():
        score_val = int(row.get("score") or 0)
        banda = str(row.get("banda") or "—")
        level = SCORING_BAND_LEVELS.get(banda, "neutral")
        badge_html = status_badge(level, banda)
        _row_id = str(row.get("id_externo", _))
        # Checkbox de selección para comparar
        _is_selected = _row_id in _compare_ids
        _cb_label = "✓ Seleccionado" if _is_selected else "Comparar"
        header = (
            f"{banda} · score {score_val}/100 · {fmt_eur(row['importe'])} — {row['titulo'][:80]}"
        )
        _is_focus = _lic_focus and str(row.get("id_externo", "")) == str(_lic_focus)
        with st.expander(header, expanded=bool(_is_focus)):
            # ── M10: marcar como leída al expandir ────────────────────
            try:
                _mark_read_notification(_ukey_v, str(row.get("id_externo", "")))
            except Exception:
                pass
            cE1, cE2 = st.columns([2, 1])
            with cE1:
                st.markdown(f"**Órgano:** {row.get('organo_contratacion', '—')}")
                st.markdown(
                    f"**Estado:** {row.get('estado_desc', '—')} · "
                    f"**Tipo proyecto:** {row.get('tipo_proyecto', '—')}"
                )
                st.markdown(f"**Módulos SAP detectados:** {row.get('modulos_str', '—')}")
                st.markdown(f"**CPV:** {row.get('cpv_desc', '—')}")
                st.markdown(
                    f"**Provincia / CCAA:** {row.get('provincia', '—')} · {row.get('ccaa', '—')}"
                )
                titulo_hl = highlight_match(str(row.get("titulo") or ""), _q)
                st.markdown(f"**Título:** {titulo_hl}", unsafe_allow_html=True)
                st.markdown("**Descripción:**")
                desc_hl = highlight_match(str(row.get("descripcion") or "—"), _q)
                st.markdown(desc_hl, unsafe_allow_html=True)
            with cE2:
                licitacion_popover(row, key=f"prev_{row.get('id_externo', _)}")
                # Botón de comparación
                if st.button(
                    _cb_label,
                    key=f"cmp_sel_{_row_id}",
                    help="Seleccionar para comparar (máx. 2)",
                    use_container_width=True,
                ):
                    _cur_ids: list[str] = list(st.session_state.get(COMPARE_IDS, []))
                    if _row_id in _cur_ids:
                        _cur_ids.remove(_row_id)
                    elif len(_cur_ids) < 2:
                        _cur_ids.append(_row_id)
                    else:
                        _cur_ids = [_cur_ids[1], _row_id]  # rotar: descartar el más antiguo
                    st.session_state[COMPARE_IDS] = _cur_ids
                    st.rerun()
                st.markdown(badge_html, unsafe_allow_html=True)
                st.metric("Score", f"{score_val}/100")
                st.metric("Importe", fmt_eur(row["importe"]))
                desg = row.get("desglose") or {}
                if isinstance(desg, dict) and desg:
                    with st.popover("📊 Desglose score", use_container_width=True):
                        for k, v in desg.items():
                            st.markdown(f"- **{k}**: `{v:+d}`")
                flags_txt = row.get("riesgo_flags", "")
                if flags_txt:
                    st.markdown(f"**⚠️ Alertas:** {flags_txt}")
                else:
                    st.markdown("**✅ Sin alertas de riesgo**")
                if row.get("url"):
                    st.link_button(
                        "📄 Ver licitación oficial", row["url"], use_container_width=True
                    )
                # ── M4: Copiar enlace profundo ────────────────────────
                import streamlit.components.v1 as _stc

                _deep_url = f"?lic={row.get('id_externo', '')}"
                _copy_js = (
                    f'<button onclick="navigator.clipboard.writeText(window.location.origin'
                    f"+window.location.pathname+'{_deep_url}').then(()=>this.textContent='✅ Copiado')\""
                    f' style="width:100%;padding:0.4rem;cursor:pointer;border:1px solid #ccc;'
                    f'border-radius:0.3rem;background:#f8f9fa;font-size:0.85rem">'
                    f"\U0001f4cb Copiar enlace</button>"
                )
                _stc.html(_copy_js, height=42)
                # ── M8: Timeline de cambios ───────────────────────────
                timeline_popover(
                    str(row.get("id_externo", "")), key=f"tl_{row.get('id_externo', _)}"
                )
                # ── Botón Seguir (watchlist) ──────────────────────────────
                _cpv_raw = str(row.get("cpv", row.get("cpv_desc", "")) or "")
                _cpv_prefix = _cpv_raw[:8].strip() if _cpv_raw else ""
                if _cpv_prefix and st.button(
                    "⭐ Seguir",
                    key=f"seguir_{row.get('id_externo', _)}",
                    help="Añadir este CPV a tu watchlist para recibir alertas",
                    use_container_width=True,
                ):
                    try:
                        import hashlib
                        import os

                        from config import settings
                        from dashboard.auth import get_current_user
                        from db.watchlist import WatchlistEntry, add_entry

                        _seed = settings.DASHBOARD_PASSWORD.get_secret_value() or os.environ.get(
                            "COMPUTERNAME", "default"
                        )
                        _ukey = hashlib.sha256(_seed.encode()).hexdigest()[:16]
                        _user = get_current_user()
                        _uid = _user.get("user_id") if _user else None
                        add_entry(
                            WatchlistEntry(
                                user_key=_ukey,
                                cpv_prefix=_cpv_prefix,
                                keyword=str(row.get("titulo", ""))[:60] or None,
                                ccaa=row.get("ccaa") or None,
                                user_id=_uid,
                            )
                        )
                        notify_success(f"CPV {_cpv_prefix} añadido a tu watchlist.")
                    except Exception as exc:
                        notify_error(f"No se pudo añadir a watchlist: {exc}")

    # Controles de paginación vista expandida
    if _det_pages > 1:
        _dp1, _dp2, _dp3 = st.columns([1, 4, 1])
        with _dp1:
            if st.button("← Anterior", key="det_prev", disabled=_det_cur == 0):
                st.session_state[_det_page_key] = _det_cur - 1
                st.rerun()
        with _dp2:
            st.caption(
                f"Mostrando {_det_start + 1}–{min(_det_start + _DETALLE_PAGE_SIZE, _total_det)} de {_total_det}"
            )
        with _dp3:
            if st.button("Siguiente →", key="det_next", disabled=_det_cur >= _det_pages - 1):
                st.session_state[_det_page_key] = _det_cur + 1
                st.rerun()
