"""CRUD para búsquedas/filtros guardados por el usuario.

La tabla ``saved_filters`` almacena snapshots serializados de ``FiltersState``
con un nombre legible definido por el usuario.
"""

from __future__ import annotations

import json
from typing import Any

from db.database import connect, now_utc_iso


def save_filter(
    user_key: str,
    name: str,
    filters_json: str,
    organization_id: int | None = None,
    visibility: str = "private",
) -> None:
    """Guarda o actualiza un filtro con nombre para el usuario.

    Si ya existe una entrada con (user_key, name) la sobreescribe.
    """
    with connect() as c:
        if organization_id is None and visibility == "private":
            c.execute(
                """
                INSERT INTO saved_filters (user_key, name, filters_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_key, name) DO UPDATE SET
                    filters_json = excluded.filters_json,
                    created_at   = excluded.created_at
                """,
                (user_key, name, filters_json, now_utc_iso()),
            )
            return
        c.execute(
            """
            INSERT INTO saved_filters
                (user_key, name, filters_json, created_at, organization_id, visibility)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_key, name) DO UPDATE SET
                filters_json = excluded.filters_json,
                created_at   = excluded.created_at,
                organization_id = excluded.organization_id,
                visibility = excluded.visibility
            """,
            (user_key, name, filters_json, now_utc_iso(), organization_id, visibility),
        )


def list_saved_filters(user_key: str, organization_id: int | None = None) -> list[dict[str, Any]]:
    """Devuelve los filtros guardados del usuario, más recientes primero."""
    with connect() as c:
        if organization_id is None:
            cur = c.execute(
                "SELECT id, name, filters_json, created_at, organization_id, visibility "
                "FROM saved_filters WHERE user_key = ? ORDER BY created_at DESC",
                (user_key,),
            )
        else:
            cur = c.execute(
                "SELECT id, name, filters_json, created_at, organization_id, visibility "
                "FROM saved_filters WHERE organization_id = ? "
                "AND (visibility = 'organization' OR user_key = ?) "
                "ORDER BY created_at DESC",
                (organization_id, user_key),
            )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def delete_saved_filter(
    filter_id: int,
    *,
    user_key: str | None = None,
    organization_id: int | None = None,
) -> None:
    """Elimina un filtro guardado por ID."""
    with connect() as c:
        if organization_id is None or user_key is None:
            c.execute("DELETE FROM saved_filters WHERE id = ?", (filter_id,))
        else:
            c.execute(
                "DELETE FROM saved_filters WHERE id = ? AND organization_id = ? "
                "AND (visibility = 'organization' OR user_key = ?)",
                (filter_id, organization_id, user_key),
            )


def filters_to_json(
    filters_state: Any, *, nav_section: str | None = None, detalle_cols: list[str] | None = None
) -> str:
    """Serializa un FiltersState a JSON string, con contexto de vista opcional."""
    d: dict[str, Any] = {
        "q": filters_state.q,
        "estados": filters_state.estados,
        "ccaas": filters_state.ccaas,
        "organos": filters_state.organos,
        "tipos_proy": filters_state.tipos_proy,
        "tecnologias": filters_state.tecnologias,
        "importe_min": filters_state.importe_min,
        "rango": (
            [filters_state.rango[0].isoformat(), filters_state.rango[1].isoformat()]
            if filters_state.rango
            else None
        ),
    }
    if nav_section:
        d["nav_section"] = nav_section
    if detalle_cols:
        d["detalle_cols"] = detalle_cols
    return json.dumps(d, ensure_ascii=False)


def json_to_session_state(filters_json: str) -> dict[str, Any]:
    """Convierte un JSON guardado a un dict de session_state keys."""
    from datetime import date

    d = json.loads(filters_json)
    ss: dict[str, Any] = {}
    if d.get("q"):
        ss["fs_q"] = d["q"]
    if d.get("estados"):
        ss["fs_estados"] = d["estados"]
    if d.get("ccaas"):
        ss["fs_ccaas"] = d["ccaas"]
    if d.get("organos"):
        ss["fs_organos"] = d["organos"]
    if d.get("tipos_proy"):
        ss["fs_tipos"] = d["tipos_proy"]
    if d.get("tecnologias"):
        ss["fs_tecnologias"] = d["tecnologias"]
    if d.get("importe_min"):
        ss["fs_imp_min"] = int(d["importe_min"])
    if d.get("rango") and len(d["rango"]) == 2:
        ss["fs_rango"] = (
            date.fromisoformat(d["rango"][0]),
            date.fromisoformat(d["rango"][1]),
        )
    # M7: restore nav section and detalle columns
    if d.get("nav_section"):
        ss["nav_section"] = d["nav_section"]
    if d.get("detalle_cols"):
        ss["detalle_cols"] = d["detalle_cols"]
    return ss
