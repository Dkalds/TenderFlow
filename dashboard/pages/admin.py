"""Página de Administración — solo accesible para usuarios con flag is_admin.

Funcionalidades:
- Gestión de la Dead Letter Queue (DLQ): ver, resolver y reintentar fallos
- Listado de usuarios registrados con opción de promover/degradar admin
- Gestión de API Keys: crear y revocar claves para la API REST
"""

from __future__ import annotations

import streamlit as st

from dashboard.auth import require_admin
from dashboard.components.states import guarded_render
from dashboard.components.tables import data_table
from dashboard.pages._base import PageContext
from db.database import connect
from db.dlq import list_unresolved, mark_matching_resolved, mark_resolved, unresolved_summary
from observability.logging import get_logger

log = get_logger(__name__)


@guarded_render
def render(ctx: PageContext) -> None:
    st.subheader("⚙️ Administración")

    if not require_admin("Esta página requiere permisos de administrador."):
        st.stop()
        return

    tab_dlq, tab_users, tab_api_keys = st.tabs(["📬 DLQ", "👥 Usuarios", "🔑 API Keys"])

    # ── Tab DLQ ───────────────────────────────────────────────────────────
    with tab_dlq:
        _render_dlq()

    # ── Tab Usuarios ──────────────────────────────────────────────────────
    with tab_users:
        _render_users()

    # ── Tab API Keys ──────────────────────────────────────────────────────
    with tab_api_keys:
        _render_api_keys()


# ---------------------------------------------------------------------------
# DLQ
# ---------------------------------------------------------------------------


def _render_dlq() -> None:
    st.markdown("#### Dead Letter Queue — Fallos pendientes")
    summary = unresolved_summary()
    if not summary:
        st.success("La DLQ está vacía. No hay fallos pendientes.", icon="✅")
    else:
        import pandas as pd

        st.dataframe(
            pd.DataFrame(summary),
            use_container_width=True,
            hide_index=True,
        )

    st.divider()
    unresolved = list_unresolved(limit=200)
    if not unresolved:
        st.info("No hay entradas sin resolver.")
        return

    import pandas as pd

    df = pd.DataFrame(unresolved)
    st.caption(f"{len(df)} entrada(s) sin resolver")

    with st.expander("Ver todas las entradas"):
        data_table(df, height=350, key="dlq_admin_table")

    st.markdown("##### Acciones")
    cols = st.columns([2, 2, 1])
    with cols[0]:
        fuente_sel = st.selectbox(
            "Fuente",
            options=["— todas —", *sorted({r["fuente"] for r in unresolved})],
            key="dlq_admin_fuente",
        )
    with cols[2]:
        if st.button("Marcar resueltos", type="primary", use_container_width=True):
            if fuente_sel == "— todas —":
                for row in unresolved:
                    try:
                        mark_resolved(int(row["id"]))
                    except Exception as e:
                        log.warning("dlq_admin_resolve_error", id=row["id"], error=str(e))
                st.success(f"Marcadas {len(unresolved)} entradas como resueltas.")
            else:
                n = mark_matching_resolved(fuente_sel)
                st.success(f"Marcadas {n} entradas de '{fuente_sel}' como resueltas.")
            st.rerun()


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------


def _render_users() -> None:
    st.markdown("#### Usuarios registrados")
    with connect() as c:
        cur = c.execute(
            "SELECT id, email, oauth_provider, display_name, created_at, is_admin "
            "FROM users ORDER BY created_at DESC LIMIT 200"
        )
        cols = [d[0] for d in cur.description]
        users = [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    if not users:
        st.info("No hay usuarios registrados aún.")
        return

    import pandas as pd

    df = pd.DataFrame(users)
    st.dataframe(
        df[["id", "email", "display_name", "oauth_provider", "created_at", "is_admin"]],
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("##### Promover / degradar admin")
    user_emails = [u["email"] for u in users if u.get("email")]
    if not user_emails:
        st.info("No hay usuarios con email registrado.")
        return

    ucol1, ucol2, ucol3 = st.columns([3, 1, 1])
    with ucol1:
        email_sel = st.selectbox("Usuario", options=user_emails, key="admin_user_sel")
    with ucol2:
        if st.button("Hacer admin", use_container_width=True):
            with connect() as c:
                c.execute("UPDATE users SET is_admin = 1 WHERE email = ?", (email_sel,))
            st.success(f"'{email_sel}' ahora es administrador.")
            st.rerun()
    with ucol3:
        if st.button("Quitar admin", use_container_width=True):
            with connect() as c:
                c.execute("UPDATE users SET is_admin = 0 WHERE email = ?", (email_sel,))
            st.success(f"'{email_sel}' ya no es administrador.")
            st.rerun()


# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------


def _render_api_keys() -> None:
    st.markdown("#### API Keys activas")
    try:
        with connect() as c:
            cur = c.execute(
                "SELECT id, name, created_at, last_used, is_active FROM api_keys ORDER BY created_at DESC"
            )
            kcols = [d[0] for d in cur.description]
            keys = [dict(zip(kcols, row, strict=False)) for row in cur.fetchall()]
    except Exception:
        st.warning("La tabla api_keys no existe todavía. Ejecuta las migraciones de BD.")
        return

    if not keys:
        st.info("No hay API Keys registradas.")
    else:
        import pandas as pd

        kdf = pd.DataFrame(keys)
        kdf["is_active"] = kdf["is_active"].apply(lambda v: "✅ Activa" if v else "🚫 Revocada")
        st.dataframe(
            kdf[["id", "name", "created_at", "last_used", "is_active"]],
            use_container_width=True,
            hide_index=True,
        )

    st.divider()
    st.markdown("##### Crear nueva API Key")
    st.caption("El token **solo se muestra una vez**. Cópialo antes de cerrar esta página.")
    key_name = st.text_input(
        "Nombre descriptivo", placeholder="ej: pipeline-produccion", key="new_api_key_name"
    )
    if st.button("Generar API Key", type="primary", disabled=not key_name):
        try:
            from api.auth import create_api_key

            token = create_api_key(key_name.strip())
            st.success("API Key creada correctamente.")
            st.code(token, language=None)
            st.warning("⚠️ Guarda este token ahora. No se puede recuperar después.")
        except Exception as e:
            st.error(f"Error al crear la clave: {e}")
        st.rerun()

    st.divider()
    st.markdown("##### Revocar API Key")
    active_keys = [k for k in keys if k.get("is_active") in (1, "✅ Activa")]
    if not active_keys:
        st.info("No hay claves activas para revocar.")
        return

    revoke_options = {
        f"{k['name']} (id={k['id']})": k["id"]
        for k in active_keys
        if k.get("is_active") not in (0, "🚫 Revocada")
    }
    if not revoke_options:
        st.info("No hay claves activas.")
        return

    rcol1, rcol2 = st.columns([3, 1])
    with rcol1:
        key_sel = st.selectbox(
            "Clave a revocar", options=list(revoke_options.keys()), key="revoke_key_sel"
        )
    with rcol2:
        if st.button("Revocar", type="secondary", use_container_width=True):
            with connect() as c:
                c.execute(
                    "UPDATE api_keys SET is_active = 0 WHERE id = ?",
                    (revoke_options[key_sel],),
                )
            st.success(f"Clave '{key_sel}' revocada.")
            st.rerun()
