"""CRUD para búsquedas/filtros guardados por el usuario.

La tabla ``saved_filters`` almacena snapshots serializados de ``FiltersState``
con un nombre legible definido por el usuario.

``organization_id`` es obligatoria y no tiene rama ``None``. La tuvo, y esa
rama era el bug de clase que documenta ``api/tenancy.py``: quien omitía el
argumento no obtenía «sin filtrar por organización» como decisión, lo
obtenía por descuido, y el repositorio caía a una query sin ámbito sin
decir nada. Ahora un llamador que la omita falla al tipar.

Desde v129 (ADR-030 fase 2) la fila lleva también ``user_id`` y la lectura es
dual: ver ``db/repositories/watchlist.py``.
"""

from __future__ import annotations

import json
from typing import Any

from db.database import connect, now_utc_iso

#: Predicado de identidad dual. Parámetros: ``(user_id, user_key, user_id)``.
_IDENT = "(user_id = %s OR (user_key = %s AND (user_id IS NULL OR %s::int IS NULL)))"


def save_filter(
    user_key: str,
    name: str,
    filters_json: str,
    organization_id: int,
    visibility: str = "private",
    *,
    user_id: int | None = None,
) -> None:
    """Guarda o actualiza un filtro con nombre para el usuario.

    Si el usuario ya tiene una vista con ese ``name`` la sobreescribe. «Ya la
    tiene» se decide con la identidad dual y no sólo con ``UNIQUE(user_key,
    name)``: tras un cambio de correo la vista antigua lleva otra clave, y el
    ``ON CONFLICT`` a secas habría creado una segunda «Mi vista» en vez de
    actualizar la que existe. Primero se intenta el ``UPDATE`` por identidad;
    el ``INSERT ... ON CONFLICT`` queda para la fila nueva y para la carrera.
    """
    now = now_utc_iso()
    with connect() as c:
        cur = c.execute(
            "UPDATE saved_filters SET filters_json = %s, created_at = %s, "
            "organization_id = %s, visibility = %s, user_id = COALESCE(user_id, %s) "
            f"WHERE {_IDENT} AND name = %s",
            (
                filters_json,
                now,
                organization_id,
                visibility,
                user_id,
                user_id,
                user_key,
                user_id,
                name,
            ),
        )
        if int(getattr(cur, "rowcount", 0) or 0) > 0:
            return
        c.execute(
            """
            INSERT INTO saved_filters
                (user_key, user_id, name, filters_json, created_at, organization_id, visibility)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(user_key, name) DO UPDATE SET
                user_id = COALESCE(saved_filters.user_id, excluded.user_id),
                filters_json = excluded.filters_json,
                created_at   = excluded.created_at,
                organization_id = excluded.organization_id,
                visibility = excluded.visibility
            """,
            (user_key, user_id, name, filters_json, now, organization_id, visibility),
        )


def list_saved_filters(
    user_key: str, organization_id: int, *, user_id: int | None = None
) -> list[dict[str, Any]]:
    """Devuelve los filtros guardados del usuario, más recientes primero."""
    with connect() as c:
        cur = c.execute(
            "SELECT id, name, filters_json, created_at, organization_id, visibility "
            "FROM saved_filters WHERE organization_id = %s "
            f"AND (visibility = 'organization' OR {_IDENT}) "
            "ORDER BY created_at DESC",
            (organization_id, user_id, user_key, user_id),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def list_own_saved_filters(user_key: str, *, user_id: int | None = None) -> list[dict[str, Any]]:
    """Todas las vistas propias del usuario, sin ámbito de organización.

    Es el camino del export GDPR (Art. 15/20): la pregunta es qué guarda el
    sistema sobre esta persona, no qué ve un equipo. Se separa de
    :func:`list_saved_filters` para que la ausencia de ámbito sea una decisión
    con nombre y no el default de un parámetro.
    """
    with connect() as c:
        cur = c.execute(
            "SELECT id, name, filters_json, created_at, organization_id, visibility "
            f"FROM saved_filters WHERE {_IDENT} ORDER BY created_at DESC",
            (user_id, user_key, user_id),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def delete_saved_filter(
    filter_id: int,
    *,
    user_key: str,
    organization_id: int,
    user_id: int | None = None,
) -> bool:
    """Elimina un filtro guardado por ID, siempre acotado a su dueño.

    ``False`` si no existe, no es del usuario o es de otra organización.

    La rama de organización llevaba ``AND (visibility = 'organization' OR
    user_key = %s)``: el ``OR`` convertía la pertenencia en *alternativa* a la
    visibilidad, no en restricción, así que cualquier miembro podía borrar la
    vista compartida de un compañero. No había fuga entre organizaciones —el
    predicado de ``organization_id`` seguía ahí— pero sí un borrado ajeno y sin
    rastro, y el docstring prometía justo lo contrario.

    De las dos formas de hacer coincidir código y promesa se elige la
    conservadora: **sólo el dueño borra**. Ver una vista compartida y poder
    destruirla son capacidades distintas; compartir no es ceder. Y el error se
    recupera de formas asimétricas: quien no puede borrar pide al dueño que lo
    haga, quien perdió una vista ajena no tiene de dónde recuperarla. Mismo
    predicado que su hermana ``services/watchlist_rules.py::delete_rule``.
    """
    with connect() as c:
        cur = c.execute(
            f"DELETE FROM saved_filters WHERE id = %s AND organization_id = %s AND {_IDENT}",
            (filter_id, organization_id, user_id, user_key, user_id),
        )
        return bool(cur.rowcount > 0)


def delete_all_for_user(user_key: str, *, user_id: int | None = None) -> int:
    """Borra todas las vistas del usuario (GDPR Art. 17). Filas borradas.

    Son dato personal (ADR-030 §D): hasta v129 el borrado de cuenta no las
    tocaba y una vista guardada sobrevivía a su dueño.
    """
    with connect() as c:
        cur = c.execute(
            f"DELETE FROM saved_filters WHERE {_IDENT}",
            (user_id, user_key, user_id),
        )
        return int(cur.rowcount)


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
