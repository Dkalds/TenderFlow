"""Persistencia del maestro de empresas (entity resolution).

CRUD sobre ``empresas``, ``empresa_aliases``, ``ute_miembros`` y
``empresa_review_queue``. La lógica de resolución (cadena NIF → alias →
fuzzy) vive en ``services.entity_resolution``; este módulo solo toca BD.

Las funciones aceptan una conexión abierta para poder agrupar el backfill
en transacciones grandes (mismo motivo que ``replace_adjudicaciones_batch``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from db.database import connect, now_utc_iso


@dataclass
class EmpresaCaches:
    """Índices en memoria para resolución en batch.

    ``nif`` mapea NIF normalizado → empresa_id (canónicos y variantes).
    ``alias`` mapea nombre normalizado → empresa_id.
    """

    nif: dict[str, int]
    alias: dict[str, int]
    alias_by_length: dict[int, set[str]]
    nif_canonico: dict[int, str | None]  # empresa_id → nif_canonico actual


def load_caches(conn: Any) -> EmpresaCaches:
    """Carga los índices NIF/alias de todas las empresas existentes."""
    nif_map: dict[str, int] = {}
    nif_canon: dict[int, str | None] = {}
    for empresa_id, nif in conn.execute("SELECT empresa_id, nif_canonico FROM empresas").fetchall():
        nif_canon[int(empresa_id)] = nif
        if nif:
            nif_map[nif] = int(empresa_id)

    alias_map: dict[str, int] = {}
    for empresa_id, alias, nif_var in conn.execute(
        "SELECT empresa_id, alias_normalizado, nif_variante FROM empresa_aliases"
    ).fetchall():
        alias_map.setdefault(alias, int(empresa_id))
        if nif_var:
            nif_map.setdefault(nif_var, int(empresa_id))
    alias_by_length: dict[int, set[str]] = {}
    for alias in alias_map:
        alias_by_length.setdefault(len(alias), set()).add(alias)
    return EmpresaCaches(
        nif=nif_map,
        alias=alias_map,
        alias_by_length=alias_by_length,
        nif_canonico=nif_canon,
    )


def create_empresa(
    conn: Any,
    *,
    nombre_canonico: str,
    nif_canonico: str | None = None,
    es_ute: bool = False,
    es_pyme: int | None = None,
) -> int:
    now = now_utc_iso()
    cur = conn.execute(
        "INSERT INTO empresas (nif_canonico, nombre_canonico, es_ute, es_pyme, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) RETURNING empresa_id",
        (nif_canonico, nombre_canonico, int(es_ute), es_pyme, now, now),
    )
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("No se pudo recuperar empresa_id tras crear la empresa")
    return int(row[0])


def add_alias(
    conn: Any,
    empresa_id: int,
    alias_normalizado: str,
    *,
    nif_variante: str | None = None,
    fuente: str = "",
    confianza: float = 1.0,
) -> None:
    """Registra una variante vista en fuente. Idempotente (índice único)."""
    conn.execute(
        "INSERT INTO empresa_aliases "
        "(empresa_id, alias_normalizado, nif_variante, fuente, confianza, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (empresa_id, alias_normalizado, COALESCE(nif_variante, '')) DO NOTHING",
        (empresa_id, alias_normalizado, nif_variante, fuente, confianza, now_utc_iso()),
    )


def set_nif_canonico_if_null(conn: Any, empresa_id: int, nif: str) -> bool:
    """Fija el NIF canónico solo si la empresa aún no tiene uno.

    Devuelve True si se actualizó. No pisa un NIF existente: un conflicto
    NIF nuevo vs NIF canónico va a la cola de revisión, no aquí.
    """
    cur = conn.execute(
        "UPDATE empresas SET nif_canonico = ?, updated_at = ? "
        "WHERE empresa_id = ? AND nif_canonico IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM empresas WHERE nif_canonico = ?) "
        "RETURNING empresa_id",
        (nif, now_utc_iso(), empresa_id, nif),
    )
    return cur.fetchone() is not None


def add_ute_member(conn: Any, ute_empresa_id: int, miembro_empresa_id: int) -> None:
    conn.execute(
        "INSERT INTO ute_miembros (ute_empresa_id, miembro_empresa_id) VALUES (?, ?) "
        "ON CONFLICT(ute_empresa_id, miembro_empresa_id) DO NOTHING",
        (ute_empresa_id, miembro_empresa_id),
    )


def link_adjudicacion(conn: Any, adjudicacion_id: int, empresa_id: int) -> None:
    conn.execute(
        "UPDATE adjudicaciones SET empresa_id = ? WHERE id = ?",
        (empresa_id, adjudicacion_id),
    )


def fetch_unlinked(
    conn: Any, limit: int, after_id: int = 0, *, fuente: str | None = None
) -> list[dict[str, Any]]:
    """Adjudicaciones sin empresa_id, paginadas por id ascendente.

    ``after_id`` permite avanzar el cursor aunque algunas filas queden sin
    resolver (p. ej. en cola de revisión) y eviten que el lote se vacíe.

    ``fuente`` acota el barrido a las adjudicaciones cuya licitación viene de
    esa fuente; ``None`` recorre la tabla entera. Hasta 2026-08 el parámetro
    no existía y el hook post-ingesta de CADA conector barría la tabla
    completa: ingerir 112 avisos de TED disparaba un recorrido del millón
    largo de filas pendientes de PSCP y agotaba el timeout del step antes de
    llegar a dedupe/eventos de contrato. El barrido global sigue siendo lo
    correcto para el backfill (scripts/backfill_empresas.py), no para el hook.

    El filtro es un semi-join contra ``licitaciones`` porque ``adjudicaciones``
    no tiene columna ``fuente`` propia; la sonda la resuelve
    ``licitaciones_pkey`` (id_externo). ``EXISTS`` y no ``JOIN`` para que el
    plan pueda seguir dirigido por ``adjudicaciones.id`` y respetar el
    ``ORDER BY`` sin sort. Necesita ``idx_lic_fuente`` sobre
    ``licitaciones(fuente)``: sin él el planner elige recorrer ``licitaciones``
    entera (~8,6 s por lote medidos en producción sobre 1,25 M de filas). Ese
    índice está en el linaje desde ``baseline002``/``v37`` pero faltaba en la BD
    de producción; lo repara ``v70_pg_missing_lic_fuente_index``.
    """
    sql = [
        "SELECT a.id, a.nombre, a.nif, a.es_pyme FROM adjudicaciones a ",
        "WHERE a.empresa_id IS NULL AND a.nombre IS NOT NULL AND a.id > ? ",
    ]
    params: list[Any] = [after_id]
    if fuente is not None:
        sql.append(
            "AND EXISTS (SELECT 1 FROM licitaciones l "
            "WHERE l.id_externo = a.licitacion_id AND l.fuente = ?) "
        )
        params.append(fuente)
    sql.append("ORDER BY a.id LIMIT ?")
    params.append(limit)

    cur = conn.execute("".join(sql), tuple(params))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def enqueue_review(
    conn: Any,
    *,
    nombre_original: str,
    alias_normalizado: str,
    nif: str | None,
    candidato_empresa_id: int | None,
    score: float,
) -> None:
    """Encola un match dudoso para revisión humana. Idempotente para pendientes."""
    conn.execute(
        "INSERT INTO empresa_review_queue "
        "(nombre_original, alias_normalizado, nif, candidato_empresa_id, score, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'pending', ?) "
        "ON CONFLICT (alias_normalizado, COALESCE(nif, ''), candidato_empresa_id) "
        "WHERE status = 'pending' DO NOTHING",
        (nombre_original, alias_normalizado, nif, candidato_empresa_id, score, now_utc_iso()),
    )


def pending_review_keys(conn: Any) -> set[tuple[str, str]]:
    """Claves (alias, nif-o-vacío) con revisión pendiente — para saltarlas en batch."""
    rows = conn.execute(
        "SELECT alias_normalizado, COALESCE(nif, '') FROM empresa_review_queue "
        "WHERE status = 'pending'"
    ).fetchall()
    return {(r[0], r[1]) for r in rows}


def list_pending_reviews(limit: int = 100) -> list[dict[str, Any]]:
    with connect() as c:
        cur = c.execute(
            "SELECT q.id, q.nombre_original, q.alias_normalizado, q.nif, q.score, "
            "       q.candidato_empresa_id, e.nombre_canonico AS candidato_nombre, "
            "       e.nif_canonico AS candidato_nif, q.created_at "
            "FROM empresa_review_queue q "
            "LEFT JOIN empresas e ON e.empresa_id = q.candidato_empresa_id "
            "WHERE q.status = 'pending' ORDER BY q.score DESC LIMIT ?",
            (limit,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def apply_review(review_id: int, *, accept: bool, resolved_by: str = "") -> int | None:
    """Resuelve una entrada de la cola.

    - accept=True: enlaza el alias al candidato y vincula las adjudicaciones
      pendientes que coincidan con (nombre, nif).
    - accept=False: crea una empresa nueva con ese alias y vincula igual.

    Devuelve el empresa_id final, o None si la entrada no existe / ya resuelta.
    """
    with connect() as c:
        row = c.execute(
            "SELECT nombre_original, alias_normalizado, nif, candidato_empresa_id "
            "FROM empresa_review_queue WHERE id = ? AND status = 'pending'",
            (review_id,),
        ).fetchone()
        if row is None:
            return None
        nombre_original, alias, nif, candidato_id = row

        if accept and candidato_id is not None:
            empresa_id = int(candidato_id)
        else:
            empresa_id = create_empresa(
                c, nombre_canonico=nombre_original.strip(), nif_canonico=nif
            )
        add_alias(c, empresa_id, alias, nif_variante=nif, fuente="review", confianza=1.0)
        if nif:
            set_nif_canonico_if_null(c, empresa_id, nif)

        # Vincular las adjudicaciones que estaban esperando esta decisión
        c.execute(
            "UPDATE adjudicaciones SET empresa_id = ? "
            "WHERE empresa_id IS NULL AND nombre = ? AND COALESCE(nif, '') = COALESCE(?, '')",
            (empresa_id, nombre_original, nif),
        )
        c.execute(
            "UPDATE empresa_review_queue SET status = ?, resolved_at = ?, resolved_by = ? "
            "WHERE id = ?",
            ("accepted" if accept else "rejected", now_utc_iso(), resolved_by, review_id),
        )
        return empresa_id


def resolution_stats() -> dict[str, Any]:
    """Métricas de cobertura del maestro: filas e importe enlazados."""
    with connect() as c:
        total, linked = c.execute(
            "SELECT COUNT(*), SUM(CASE WHEN empresa_id IS NOT NULL THEN 1 ELSE 0 END) "
            "FROM adjudicaciones"
        ).fetchone()
        imp_total, imp_linked = c.execute(
            "SELECT COALESCE(SUM(importe_adjudicado), 0), "
            "       COALESCE(SUM(CASE WHEN empresa_id IS NOT NULL THEN importe_adjudicado ELSE 0 END), 0) "
            "FROM adjudicaciones"
        ).fetchone()
        n_empresas = c.execute("SELECT COUNT(*) FROM empresas").fetchone()[0]
        n_pending = c.execute(
            "SELECT COUNT(*) FROM empresa_review_queue WHERE status = 'pending'"
        ).fetchone()[0]
    total = int(total or 0)
    linked = int(linked or 0)
    return {
        "adjudicaciones_total": total,
        "adjudicaciones_enlazadas": linked,
        "pct_filas": (linked / total * 100) if total else 0.0,
        "importe_total": float(imp_total or 0),
        "importe_enlazado": float(imp_linked or 0),
        "pct_importe": (float(imp_linked) / float(imp_total) * 100) if imp_total else 0.0,
        "empresas": int(n_empresas),
        "revisiones_pendientes": int(n_pending),
    }
