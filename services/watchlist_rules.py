"""Reglas de watchlist por criterio (keyword/CPV/importe/CCAA) — persistencia
server-side.

A diferencia de la watchlist de empresas (v36, ``services/watchlist.py``, cuyo eje
es la empresa), estas reglas vigilan **criterios de búsqueda**. Sustituyen el
``localStorage`` del frontend de mi-watchlist (RFC ux-mi-watchlist; ADR-014 §2: el
estado de usuario es server-side, ``localStorage`` solo caché/migración one-shot).

Este módulo cubre el **CRUD**. El *matching* sobre el dataset completo (reusando el
repositorio de licitaciones con ``_escape_like``) y el *job de alertas por
frecuencia* (→ ``notifications``) se añaden en increments posteriores.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select

from db.database import connect, connect_read
from db.models import compile_query, licitaciones
from db.repositories.base import rows_to_dicts

Frequency = Literal["immediate", "daily", "weekly"]


class WatchlistRule(BaseModel):
    """Regla de seguimiento por criterio. ``id`` es ``None`` hasta persistir."""

    id: int | None = None
    nombre: str | None = None
    keyword: str | None = None
    cpv: str | None = None
    min_importe: float | None = None
    ccaa: str | None = None
    frequency: Frequency = "daily"
    active: bool = True
    organization_id: int | None = None
    visibility: Literal["private", "organization"] = "private"


def create_rule(
    user_key: str,
    rule: WatchlistRule,
    *,
    user_id: int | None = None,
    organization_id: int | None = None,
    visibility: str = "private",
) -> int:
    """Persiste una regla nueva y devuelve su id."""
    with connect() as c:
        cur = c.execute(
            "INSERT INTO watchlist_rules "
            "(user_key, user_id, nombre, keyword, cpv, min_importe, ccaa, "
            " frequency, active, organization_id, visibility) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_key,
                user_id,
                rule.nombre,
                rule.keyword,
                rule.cpv,
                rule.min_importe,
                rule.ccaa,
                rule.frequency,
                1 if rule.active else 0,
                organization_id,
                visibility,
            ),
        )
        rid = cur.lastrowid
    return int(rid) if rid is not None else 0


def list_rules(user_key: str, organization_id: int | None = None) -> list[WatchlistRule]:
    """Reglas de un usuario, más recientes primero."""
    with connect() as c:
        if organization_id is None:
            rows = c.execute(
                "SELECT id, nombre, keyword, cpv, min_importe, ccaa, frequency, active, "
                "organization_id, visibility FROM watchlist_rules WHERE user_key = ? "
                "ORDER BY created_at DESC, id DESC",
                (user_key,),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT id, nombre, keyword, cpv, min_importe, ccaa, frequency, active, "
                "organization_id, visibility FROM watchlist_rules "
                "WHERE organization_id = ? "
                "AND (visibility = 'organization' OR user_key = ?) "
                "ORDER BY created_at DESC, id DESC",
                (organization_id, user_key),
            ).fetchall()
    return [
        WatchlistRule(
            id=row[0],
            nombre=row[1],
            keyword=row[2],
            cpv=row[3],
            min_importe=row[4],
            ccaa=row[5],
            frequency=row[6],
            active=bool(row[7]),
            organization_id=row[8],
            visibility=row[9],
        )
        for row in rows
    ]


def update_rule(
    user_key: str,
    rule_id: int,
    rule: WatchlistRule,
    organization_id: int | None = None,
) -> bool:
    """Actualiza una regla propia. ``False`` si no existe o no es del usuario."""
    values = (
        rule.nombre,
        rule.keyword,
        rule.cpv,
        rule.min_importe,
        rule.ccaa,
        rule.frequency,
        1 if rule.active else 0,
    )
    with connect() as c:
        if organization_id is None:
            cur = c.execute(
                "UPDATE watchlist_rules SET "
                "nombre = ?, keyword = ?, cpv = ?, min_importe = ?, ccaa = ?, "
                "frequency = ?, active = ? "
                "WHERE id = ? AND user_key = ?",
                (*values, rule_id, user_key),
            )
        else:
            cur = c.execute(
                "UPDATE watchlist_rules SET "
                "nombre = ?, keyword = ?, cpv = ?, min_importe = ?, ccaa = ?, "
                "frequency = ?, active = ? "
                "WHERE id = ? AND user_key = ? AND organization_id = ?",
                (*values, rule_id, user_key, organization_id),
            )
        return bool(cur.rowcount > 0)


def set_active(user_key: str, rule_id: int, active: bool) -> bool:
    """Activa o pausa una regla propia."""
    with connect() as c:
        cur = c.execute(
            "UPDATE watchlist_rules SET active = ? WHERE id = ? AND user_key = ?",
            (1 if active else 0, rule_id, user_key),
        )
        return bool(cur.rowcount > 0)


def delete_rule(user_key: str, rule_id: int, organization_id: int | None = None) -> bool:
    """Borra una regla propia. ``False`` si no existe o no es del usuario."""
    with connect() as c:
        if organization_id is None:
            cur = c.execute(
                "DELETE FROM watchlist_rules WHERE id = ? AND user_key = ?",
                (rule_id, user_key),
            )
        else:
            cur = c.execute(
                "DELETE FROM watchlist_rules WHERE id = ? AND user_key = ? AND organization_id = ?",
                (rule_id, user_key, organization_id),
            )
        return bool(cur.rowcount > 0)


def delete_all_for_user(user_key: str) -> int:
    """Borra todas las reglas del usuario (GDPR). Devuelve el numero de filas borradas."""
    with connect() as c:
        cur = c.execute("DELETE FROM watchlist_rules WHERE user_key = ?", (user_key,))
        return int(cur.rowcount)


# ---------------------------------------------------------------------------
# Matching sobre el dataset completo
#
# RFC ux-mi-watchlist: el matching aplica keyword + CPV + min_importe + ccaa
# (no solo keyword/ccaa como el frontend), y el conteo se calcula en backend
# sobre TODO el dataset (no un ``limit=20`` cliente). SQLAlchemy Core →
# parametrizado (sin SQL string-built, sin S608).
# ---------------------------------------------------------------------------

_MATCH_COLS = (
    licitaciones.c.id_externo,
    licitaciones.c.titulo,
    licitaciones.c.organo_contratacion,
    licitaciones.c.importe,
    licitaciones.c.cpv,
    licitaciones.c.ccaa,
    licitaciones.c.estado,
    licitaciones.c.fecha_publicacion,
    licitaciones.c.url,
)


def _escape_like(s: str) -> str:
    """Escapa wildcards LIKE (%, _) del input de usuario."""
    return s.replace("%", r"\%").replace("_", r"\_")


def _rule_clauses(rule: WatchlistRule) -> list[Any]:
    """Traduce los filtros de la regla a condiciones SQLAlchemy.

    Aplica TODOS los criterios: keyword (título/descripción), cpv (prefijo),
    min_importe (>=) y ccaa (=). El CPV deja de ser un control muerto.
    """
    clauses: list[Any] = []
    if rule.keyword:
        like = f"%{_escape_like(rule.keyword)}%"
        clauses.append(
            or_(
                licitaciones.c.titulo.like(like),
                licitaciones.c.descripcion.like(like),
            )
        )
    if rule.cpv:
        clauses.append(licitaciones.c.cpv.like(f"{_escape_like(rule.cpv)}%"))
    if rule.min_importe is not None:
        clauses.append(licitaciones.c.importe >= rule.min_importe)
    if rule.ccaa:
        clauses.append(licitaciones.c.ccaa == rule.ccaa)
    return clauses


def count_matches(rule: WatchlistRule) -> int:
    """Conteo de matches sobre el dataset COMPLETO (no un ``limit=20`` cliente)."""
    clauses = _rule_clauses(rule)
    stmt = select(func.count()).select_from(licitaciones)
    if clauses:
        stmt = stmt.where(and_(*clauses))
    sql, params = compile_query(stmt)
    with connect_read() as c:
        row = c.execute(sql, params).fetchone()
    return int(row[0]) if row else 0


def list_matches(rule: WatchlistRule, *, limit: int = 50) -> list[dict[str, Any]]:
    """Matches de la regla (preview en vivo), más recientes primero."""
    clauses = _rule_clauses(rule)
    stmt = select(*_MATCH_COLS).select_from(licitaciones)
    if clauses:
        stmt = stmt.where(and_(*clauses))
    stmt = stmt.order_by(licitaciones.c.fecha_publicacion.desc()).limit(limit)
    sql, params = compile_query(stmt)
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))


def matches_since(
    rule: WatchlistRule, since: str | None, *, limit: int = 50
) -> list[dict[str, Any]]:
    """Como ``list_matches`` pero solo licitaciones con ``fecha_publicacion``
    posterior a ``since`` (fecha ISO ``YYYY-MM-DD``). Para el job de alertas:
    ver únicamente lo nuevo desde la última notificación."""
    clauses = _rule_clauses(rule)
    if since:
        clauses.append(licitaciones.c.fecha_publicacion > since)
    stmt = select(*_MATCH_COLS).select_from(licitaciones)
    if clauses:
        stmt = stmt.where(and_(*clauses))
    stmt = stmt.order_by(licitaciones.c.fecha_publicacion.desc()).limit(limit)
    sql, params = compile_query(stmt)
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))
