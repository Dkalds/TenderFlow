"""Página Observabilidad — runs del pipeline, DLQ y estado del sistema."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard.auth import current_user_is_admin
from dashboard.components.kpi import kpi_card
from dashboard.components.states import empty_state, guarded_render
from dashboard.components.tables import data_table
from dashboard.kpi_config import KPI_FORMULAS
from dashboard.pages._base import PageContext
from dashboard.stats import calidad_dato
from db.audit import list_recent as audit_list_recent
from db.database import connect
from db.dlq import list_unresolved, mark_matching_resolved, mark_resolved, unresolved_summary


@guarded_render
def render(ctx: PageContext) -> None:
    if not current_user_is_admin():
        st.warning("Sección restringida a administradores.")
        st.stop()

    st.subheader("Observabilidad")
    st.caption(
        "Estado del pipeline de extracción: runs recientes, métricas y "
        "cola de fallos pendientes de resolver."
    )

    with connect() as c:
        cur = c.execute(
            "SELECT run_id, started_at, ended_at, duration_ms, status, "
            "months_attempted, months_ok, months_failed, "
            "licitaciones_nuevas, licitaciones_actualizadas, "
            "adjudicaciones, errores_parseo, errores_descarga, notas "
            "FROM extraction_runs ORDER BY started_at DESC LIMIT 200"
        )
        runs = pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])

    if runs.empty:
        empty_state("📉", "Sin runs registrados", "Ejecuta el pipeline para ver métricas aquí.")
        return

    runs["started_at"] = pd.to_datetime(runs["started_at"], errors="coerce", utc=True)
    runs["ended_at"] = pd.to_datetime(runs["ended_at"], errors="coerce", utc=True)
    runs["duration_s"] = (runs["duration_ms"] / 1000).round(1)

    last = runs.iloc[0]
    hoy = pd.Timestamp.now("UTC")
    last7 = runs[runs["started_at"] >= (hoy - pd.Timedelta(days=7))]
    last30 = runs[runs["started_at"] >= (hoy - pd.Timedelta(days=30))]
    prev_week = runs[
        (runs["started_at"] >= (hoy - pd.Timedelta(days=14)))
        & (runs["started_at"] < (hoy - pd.Timedelta(days=7)))
    ]

    # ── Fila 1: estado del último run y salud reciente ────────────
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(
            kpi_card(
                "Último run",
                str(last["status"]).upper(),
                delta=last["started_at"].strftime("%Y-%m-%d %H:%M")
                if pd.notna(last["started_at"])
                else "",
                icon="🏁",
            ),
            unsafe_allow_html=True,
        )
    with k2:
        ok_rate_7 = (last7["status"] == "ok").sum() / max(len(last7), 1) * 100
        st.markdown(
            kpi_card(
                "Éxito 7d",
                f"{ok_rate_7:.0f}%",
                icon="✅",
                delta=f"{len(last7)} runs",
                delta_up=ok_rate_7 >= 90,
            ),
            unsafe_allow_html=True,
        )
    with k3:
        ok_rate_30 = (last30["status"] == "ok").sum() / max(len(last30), 1) * 100
        st.markdown(
            kpi_card(
                "Éxito 30d",
                f"{ok_rate_30:.0f}%",
                icon="�",
                delta=f"{len(last30)} runs",
                delta_up=ok_rate_30 >= 90,
            ),
            unsafe_allow_html=True,
        )
    with k4:
        st.markdown(
            kpi_card("Duración último run", f"{last['duration_s'] or 0:.1f}s", icon="⏱"),
            unsafe_allow_html=True,
        )

    # ── Fila 2: volumen procesado (nuevas + acumulado) ────────────
    k5, k6, k7, k8 = st.columns(4)
    with k5:
        st.markdown(
            kpi_card("Nuevas último run", f"{int(last['licitaciones_nuevas']):,}", icon="🆕"),
            unsafe_allow_html=True,
        )
    with k6:
        nuevas_7d = int(last7["licitaciones_nuevas"].fillna(0).sum())
        nuevas_prev = int(prev_week["licitaciones_nuevas"].fillna(0).sum())
        delta_week_pct = (nuevas_7d - nuevas_prev) / nuevas_prev * 100 if nuevas_prev else 0.0
        st.markdown(
            kpi_card(
                "Nuevas (7d)",
                f"{nuevas_7d:,}",
                delta=f"{delta_week_pct:+.1f}% vs semana anterior",
                delta_up=delta_week_pct >= 0,
                icon="📥",
            ),
            unsafe_allow_html=True,
        )
    with k7:
        total_proc = int(runs["licitaciones_nuevas"].fillna(0).sum())
        st.markdown(
            kpi_card(
                "Total procesadas",
                f"{total_proc:,}",
                delta=f"en {len(runs)} runs",
                icon="🗃️",
            ),
            unsafe_allow_html=True,
        )
    with k8:
        avg_dur = float(last30["duration_s"].mean() or 0)
        st.markdown(
            kpi_card(
                "Duración media 30d",
                f"{avg_dur:.1f}s",
                delta="promedio por run",
                icon="⌛",
            ),
            unsafe_allow_html=True,
        )

    # ── Calidad del dato ───────────────────────────────────────────
    _render_calidad_dato(ctx, last, runs)

    st.markdown("#### Duración e incidencias por run")
    fig = px.scatter(
        runs.head(60).sort_values("started_at"),
        x="started_at",
        y="duration_s",
        color="status",
        size="licitaciones_nuevas",
        hover_data=["months_ok", "months_failed", "errores_parseo"],
        template=ctx.plotly_template,
        labels={"started_at": "Inicio", "duration_s": "Duración (s)"},
    )
    fig.update_layout(height=360, margin=dict(t=20, b=10, l=10, r=10))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Runs recientes")
    data_table(
        runs.head(50),
        height=360,
        column_config={
            "started_at": st.column_config.DatetimeColumn("Inicio"),
            "ended_at": st.column_config.DatetimeColumn("Fin"),
            "duration_s": st.column_config.NumberColumn("Duración (s)", format="%.1f"),
            "licitaciones_nuevas": st.column_config.NumberColumn("Nuevas"),
            "licitaciones_actualizadas": st.column_config.NumberColumn("Actualizadas"),
        },
    )

    st.markdown("#### Dead Letter Queue")
    summary = unresolved_summary()
    if summary:
        st.caption("Resumen por fuente y fase")
        data_table(pd.DataFrame(summary), height=180)
    failures = list_unresolved(limit=200)
    if not failures:
        st.success("No hay fallos sin resolver. ✅")
        return

    dlq_df = pd.DataFrame(failures)
    st.warning(f"{len(dlq_df)} fallos sin resolver")
    data_table(dlq_df, height=320)

    with st.expander("Acciones DLQ"):
        from dashboard.auth import require_admin

        if not require_admin("Solo los administradores pueden resolver fallos del DLQ."):
            return
        ids = dlq_df["id"].astype(int).tolist()
        pick = st.selectbox("ID fallo", ids, key="dlq_pick")
        c_resolve, c_retry = st.columns(2)
        with c_resolve:
            if st.button("Marcar resuelto"):
                mark_resolved(int(pick))
                st.success(f"Fallo #{pick} marcado como resuelto.")
                st.rerun()
        with c_retry:
            if st.button("Reintentar fallo"):
                from scheduler.dlq_actions import retry_failure

                try:
                    result = retry_failure(int(pick))
                    st.success(f"Retry #{pick}: {result['status']}")
                    st.rerun()
                except Exception as exc:
                    st.error(f"No se pudo reintentar: {exc}")

        st.divider()
        group_labels = [
            f"{row['fuente']} / {row['scope'] or 'sin_scope'} ({row['n']})" for row in summary
        ]
        if group_labels:
            selected_group = st.selectbox("Resolver grupo", group_labels, key="dlq_group")
            idx = group_labels.index(selected_group)
            group = summary[idx]
            if st.button("Marcar grupo resuelto"):
                n = mark_matching_resolved(group["fuente"], group["scope"] or None)
                st.success(f"{n} fallo(s) marcados como resueltos.")
                st.rerun()

    # ── Audit Log ────────────────────────────────────────────────────────
    st.markdown("#### Audit Log")
    st.caption("Últimas 500 acciones de usuario registradas.")
    audit_rows = audit_list_recent(limit=500)
    if audit_rows:
        audit_df = pd.DataFrame(audit_rows)
        audit_df["created_at"] = pd.to_datetime(audit_df["created_at"], errors="coerce", utc=True)

        # Filtros rápidos
        acol1, acol2, acol3 = st.columns(3)
        with acol1:
            acciones_disponibles = [
                "(todas)",
                *sorted(audit_df["action"].dropna().unique().tolist()),
            ]
            filtro_accion = st.selectbox(
                "Filtrar por acción", acciones_disponibles, key="audit_accion"
            )
        with acol2:
            usuarios_disponibles = [
                "(todos)",
                *sorted(audit_df["user_key"].dropna().unique().tolist()),
            ]
            filtro_usuario = st.selectbox(
                "Filtrar por usuario", usuarios_disponibles, key="audit_usuario"
            )
        with acol3:
            rango = st.date_input("Rango de fechas", value=[], key="audit_rango")

        mask = pd.Series(True, index=audit_df.index)
        if filtro_accion != "(todas)":
            mask &= audit_df["action"] == filtro_accion
        if filtro_usuario != "(todos)":
            mask &= audit_df["user_key"] == filtro_usuario
        if isinstance(rango, (list, tuple)) and len(rango) == 2:
            f_ini = pd.Timestamp(rango[0], tz="UTC")
            f_fin = pd.Timestamp(rango[1], tz="UTC") + pd.Timedelta(days=1)
            mask &= (audit_df["created_at"] >= f_ini) & (audit_df["created_at"] < f_fin)

        filtered_audit = audit_df[mask]
        st.caption(f"{len(filtered_audit):,} registros filtrados de {len(audit_df):,}")
        data_table(
            filtered_audit,
            height=340,
            column_config={
                "created_at": st.column_config.DatetimeColumn("Fecha"),
                "action": st.column_config.TextColumn("Acción"),
                "detail": st.column_config.TextColumn("Detalle"),
                "user_key": st.column_config.TextColumn("Usuario"),
                "session_hash": st.column_config.TextColumn("Sesión"),
            },
        )
    else:
        st.info("Sin acciones registradas aún.")

    # ── Gestión de usuarios ──────────────────────────────────────────────
    st.markdown("#### Gestión de usuarios")
    _render_user_management()


def _render_user_management() -> None:
    """Sección admin para listar, dar/quitar admin y desactivar usuarios."""
    from db.users import deactivate_user, list_users, set_admin

    try:
        users = list_users(limit=200)
    except Exception as exc:
        st.warning(f"No se pudo cargar la tabla de usuarios: {exc}")
        return

    if not users:
        st.info("No hay usuarios registrados (solo se registran accesos vía OAuth).")
        return

    users_df = pd.DataFrame(users)
    users_df["is_admin"] = users_df["is_admin"].astype(bool)
    users_df["last_access"] = pd.to_datetime(users_df["last_access"], errors="coerce", utc=True)
    users_df["created_at"] = pd.to_datetime(users_df["created_at"], errors="coerce", utc=True)

    data_table(
        users_df,
        height=280,
        column_config={
            "id": st.column_config.NumberColumn("ID", width="small"),
            "email": st.column_config.TextColumn("Email"),
            "display_name": st.column_config.TextColumn("Nombre"),
            "oauth_provider": st.column_config.TextColumn("Proveedor"),
            "is_admin": st.column_config.CheckboxColumn("Admin"),
            "created_at": st.column_config.DatetimeColumn("Registrado"),
            "last_access": st.column_config.DatetimeColumn("Último acceso"),
        },
    )

    with st.expander("Acciones de usuario"):
        user_options = [f"[{u['id']}] {u.get('email', '—')}" for u in users]
        selected = st.selectbox("Usuario", user_options, key="user_mgmt_select")
        selected_id = int(selected.split("]")[0].lstrip("["))

        selected_user = next((u for u in users if u["id"] == selected_id), None)
        if selected_user:
            current_admin = bool(selected_user.get("is_admin"))
            ua1, ua2 = st.columns(2)
            with ua1:
                new_label = "Quitar admin" if current_admin else "Dar admin"
                if st.button(new_label, key="user_toggle_admin"):
                    set_admin(selected_id, not current_admin)
                    st.success(f"Usuario #{selected_id} actualizado.")
                    st.rerun()
            with ua2:
                if st.button("⚠️ Desactivar usuario", key="user_deactivate", type="secondary"):
                    deactivate_user(selected_id)
                    st.success(f"Usuario #{selected_id} eliminado.")
                    st.rerun()


def _render_calidad_dato(ctx: PageContext, last_run, runs) -> None:
    """Sección con KPIs de completitud del dataset y frescura del scrape."""
    st.markdown("#### Calidad del dato")
    q = calidad_dato(ctx.df_full)

    # Antigüedad del último scrape en horas
    antiguedad_h = 0.0
    if pd.notna(last_run["started_at"]):
        hoy = pd.Timestamp.now("UTC")
        started = pd.Timestamp(last_run["started_at"])
        if started.tzinfo is None:
            started = started.tz_localize("UTC")
        delta = hoy - started
        antiguedad_h = float(delta.total_seconds() / 3600)

    q1, q2, q3, q4, q5 = st.columns(5)
    with q1:
        st.markdown(
            kpi_card(
                "CPV válido",
                f"{q['pct_cpv_valido']:.0f}%",
                delta="≥8 dígitos",
                delta_up=q["pct_cpv_valido"] >= 90,
                icon="🏷",
                tooltip=KPI_FORMULAS["calidad_cpv"],
            ),
            unsafe_allow_html=True,
        )
    with q2:
        st.markdown(
            kpi_card(
                "Importe presente",
                f"{q['pct_importe']:.0f}%",
                delta_up=q["pct_importe"] >= 80,
                icon="💶",
                tooltip=KPI_FORMULAS["calidad_importe"],
            ),
            unsafe_allow_html=True,
        )
    with q3:
        st.markdown(
            kpi_card(
                "Fecha publicación",
                f"{q['pct_fecha_pub']:.0f}%",
                delta_up=q["pct_fecha_pub"] >= 98,
                icon="📅",
                tooltip=KPI_FORMULAS["calidad_fechas"],
            ),
            unsafe_allow_html=True,
        )
    with q4:
        st.markdown(
            kpi_card(
                "Título válido",
                f"{q['pct_titulo']:.0f}%",
                delta=">10 chars",
                delta_up=q["pct_titulo"] >= 95,
                icon="📝",
                tooltip="% licitaciones con título no vacío de más de 10 caracteres.",
            ),
            unsafe_allow_html=True,
        )
    with q5:
        st.markdown(
            kpi_card(
                "Antigüedad scrape",
                f"{antiguedad_h:.1f}h",
                delta="desde último run",
                delta_up=antiguedad_h < 36,
                icon="🕐",
                tooltip=KPI_FORMULAS["antiguedad_scrape"],
            ),
            unsafe_allow_html=True,
        )
    _ = runs  # reservado por si queremos sparkline de runs/día
