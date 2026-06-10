"""Componentes de layout — topbar unificada, footer y branding.

Premium refresh: el header tradicional + top-nav se unifican en una sola
``topbar`` fija (logo · nav slot · meta pill · acciones). El logo ya no
está en el sidebar, lo que libera espacio para los filtros.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.components.icons import LOGO_SVG, icon
from dashboard.data_loader import load_extracciones


def _format_last_updated(ts: Any) -> str:
    """Devuelve un texto humano corto para la pill de 'Última actualización'."""
    if ts is None:
        return "sin datos"
    if isinstance(ts, str):
        ts = pd.to_datetime(ts, utc=True, errors="coerce")
    if pd.isna(ts):
        return "sin datos"
    if hasattr(ts, "tzinfo") and ts.tzinfo is None:
        ts = ts.tz_localize("UTC")

    now = datetime.now(UTC)
    delta = now - (ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts)
    secs = int(delta.total_seconds())
    if secs < 60:
        return "hace segundos"
    if secs < 3600:
        return f"hace {secs // 60} min"
    if secs < 86400:
        return f"hace {secs // 3600} h"
    days = secs // 86400
    return f"hace {days} d" if days < 30 else ts.strftime("%Y-%m-%d")


def render_topbar_brand(tagline: str = "Sector público · ES") -> None:
    """Renderiza el bloque brand del topbar (logo + nombre + tagline)."""
    st.markdown(
        f'<div class="topbar-brand">'
        f'<span class="brand-logo">{LOGO_SVG}</span>'
        f'<span class="brand-name">Licitaciones</span>'
        f'<span class="brand-tag">{tagline}</span>'
        f"</div>",
        unsafe_allow_html=True,
    )


def render_topbar(last_updated: Any = None) -> bool:
    """Topbar premium: brand + meta pill + acciones (refresh, theme toggle).

    Devuelve el estado del toggle de tema (False = dark, True = light) para
    que el caller inyecte el atributo ``data-theme`` correspondiente.

    Layout: usa st.columns con anchos relativos para alinear los slots.
    """
    from dashboard.session_keys import UI_LIGHT_MODE, USER_NAME

    last_str = _format_last_updated(last_updated)
    is_light: bool = st.session_state.get(UI_LIGHT_MODE, False)

    # Apertura del wrapper visual de la topbar
    st.markdown('<div class="topbar">', unsafe_allow_html=True)

    col_brand, col_spacer, col_meta, col_theme, col_refresh = st.columns(
        [3, 4, 3.5, 0.6, 0.6], gap="small", vertical_alignment="center"
    )
    with col_brand:
        render_topbar_brand()
    with col_spacer:
        st.markdown('<div class="topbar-spacer"></div>', unsafe_allow_html=True)
    with col_meta:
        _user_name = st.session_state.get(USER_NAME, "")
        _user_str = f" · {_user_name}" if _user_name else ""
        st.markdown(
            '<div style="display:flex;justify-content:flex-end;align-items:center;height:100%">'
            '<span class="topbar-meta">'
            '<span class="pulse-dot"></span>'
            f"{icon('clock', 12)} Actualizado {last_str}{_user_str}"
            "</span></div>",
            unsafe_allow_html=True,
        )
    with col_theme:
        theme_icon = "☀" if is_light else "◑"
        theme_help = "Cambiar a tema oscuro" if is_light else "Cambiar a tema claro"
        if st.button(
            theme_icon,
            use_container_width=True,
            help=theme_help,
            key="header_theme",
        ):
            st.session_state[UI_LIGHT_MODE] = not is_light
            st.rerun()
    with col_refresh:
        if st.button(
            "↻",
            use_container_width=True,
            help="Refrescar caché de datos",
            key="header_refresh",
        ):
            st.cache_data.clear()
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

    return is_light


def render_export_popover(df: pd.DataFrame) -> None:
    """Exportación global eliminada — función mantenida por compatibilidad."""
    return


# ── Backward-compat shims ────────────────────────────────────────────────


def render_sidebar_brand() -> None:
    """Compat: en el nuevo layout el brand vive en la topbar.

    Mantenida para no romper imports externos. Renderiza un divisor sutil
    con un caption fino para empezar el sidebar de forma limpia.
    """
    st.markdown(
        '<div style="height:6px"></div>',
        unsafe_allow_html=True,
    )


def render_notification_bell(
    df_full: pd.DataFrame,
    user_key: str,
    *,
    since_days: int = 7,
) -> None:
    """Campana de notificaciones en la topbar con badge de no leídas.

    Muestra un popover con las últimas licitaciones nuevas (últimos ``since_days``
    días). El badge indica cuántas no han sido vistas aún por el usuario.

    Args:
        df_full: DataFrame completo de licitaciones (sin filtrar).
        user_key: Clave opaca del usuario actual.
        since_days: Ventana de tiempo para considerar licitaciones nuevas.
    """
    try:
        from services.notifications import get_unread_ids, mark_all_read

        hoy = pd.Timestamp.now(tz="UTC")
        fpub = df_full["fecha_publicacion"]
        if getattr(fpub.dt, "tz", None) is None:
            hoy = hoy.tz_localize(None)
        desde = hoy - pd.Timedelta(days=since_days)
        nuevas = df_full[fpub >= desde]

        candidate_ids: list[str] = nuevas["id_externo"].dropna().astype(str).tolist()
        unread_ids = get_unread_ids(user_key, candidate_ids)
        n_unread = len(unread_ids)

        _badge_html = (
            f'<span style="position:absolute;top:-4px;right:-4px;background:#E21836;'
            f"color:#fff;border-radius:50%;width:16px;height:16px;font-size:0.68rem;"
            f"display:flex;align-items:center;justify-content:center;"
            f'font-weight:700;line-height:1">{min(n_unread, 99)}</span>'
            if n_unread > 0
            else ""
        )

        st.markdown(
            """
            <style>
            div[data-testid="stPopover"]:has(button[title="Notificaciones recientes"]) {
                position: fixed; top: 8px; right: 52px; z-index: 9998;
            }
            div[data-testid="stPopover"]:has(button[title="Notificaciones recientes"]) > div {
                position: relative; display: inline-block;
            }
            div[data-testid="stPopover"]:has(button[title="Notificaciones recientes"]) button {
                background: var(--color-bg-elev-2) !important;
                border: 1px solid var(--color-border-card) !important;
                min-height: 0 !important; height: 1.9em !important;
                padding: 4px 8px !important; font-size: 0.9rem !important;
                border-radius: 6px !important;
            }
            </style>
            <style>.notif-badge-wrap{position:relative;display:inline-block}</style>
            """,
            unsafe_allow_html=True,
        )

        with st.popover("🔔", help="Notificaciones recientes"):
            st.markdown(
                f"**Novedades últimos {since_days} días** "
                f"({n_unread} no leídas de {len(candidate_ids)})"
            )
            if nuevas.empty:
                st.caption("Sin licitaciones nuevas en este periodo.")
            else:
                _show = nuevas.sort_values("fecha_publicacion", ascending=False).head(10)
                for _, _nr in _show.iterrows():
                    _nid = str(_nr.get("id_externo", ""))
                    _is_unread = _nid in unread_ids
                    _dot = "🔵 " if _is_unread else ""
                    st.markdown(
                        f"{_dot}**{str(_nr.get('titulo', '—'))[:60]}**  \n"
                        f"_{str(_nr.get('organo_contratacion', '—'))[:40]}_ · "
                        f"{fmt_eur(_nr.get('importe'))}"
                    )
                if n_unread > 0 and st.button("Marcar todo como leído", key="notif_mark_read"):
                    mark_all_read(user_key, unread_ids)
                    st.rerun()

        # ── M9: Browser push notification via JS Notification API ─────
        from dashboard.session_keys import BROWSER_NOTIF_SENT

        if n_unread > 0 and not st.session_state.get(BROWSER_NOTIF_SENT):
            import streamlit.components.v1 as _stc_notif

            _notif_title = f"{n_unread} licitaciones nuevas"
            _notif_body = "Tienes licitaciones sin revisar en el dashboard SAP."
            _stc_notif.html(
                f"""<script>
                (function() {{
                    if (!("Notification" in window)) return;
                    function show() {{
                        new Notification("{_notif_title}", {{
                            body: "{_notif_body}",
                            icon: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🔔</text></svg>"
                        }});
                    }}
                    if (Notification.permission === "granted") {{ show(); }}
                    else if (Notification.permission !== "denied") {{
                        Notification.requestPermission().then(function(p) {{
                            if (p === "granted") show();
                        }});
                    }}
                }})();
                </script>""",
                height=0,
            )
            st.session_state[BROWSER_NOTIF_SENT] = True
    except Exception:
        pass  # No romper el topbar si la DB no está lista


def fmt_eur(value: Any) -> str:
    """Helper local para formatear euros (evitar import circular)."""
    try:
        from dashboard.utils.format import fmt_eur as _fmt

        return _fmt(value)
    except Exception:
        if value is None:
            return "—"
        return f"{float(value):,.0f} €"
    """Footer con metadatos de última extracción y atribución de fuente."""
    st.divider()
    ext = load_extracciones()
    if not ext.empty:
        st.markdown(
            f'<div style="font-size:0.78rem;color:var(--color-text-muted);'
            f'display:flex;align-items:center;gap:6px">'
            f"{icon('database', 12)}"
            f"<span>Última extracción: {ext.iloc[0]['fecha']} — fuente "
            f"{ext.iloc[0]['fuente']} ({ext.iloc[0]['nuevas']} nuevas)</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    st.caption(
        "Fuente oficial: contrataciondelestado.es · Datos reutilizados al amparo de la Ley 37/2007"
    )
