"""Resoluciones de recursos contractuales — TACRC (Fase 5.3, RFC 20260611-1).

El TACRC no produce licitaciones: produce resoluciones que afectan al ciclo
de vida de contratos ya ingeridos (suspensiones, anulaciones de adjudicación,
retroacciones). Este módulo gestiona su persistencia y su integración con la
Fase 4:

- Upsert idempotente sobre ``resoluciones_recurso``
  (``UNIQUE(tribunal, numero_resolucion)``).
- **Vinculación débil** a licitaciones por expediente + órgano normalizado
  (la misma normalización que el dedupe de 5.2). Sin match, la resolución se
  guarda igualmente con ``licitacion_id NULL`` — feed de jurisprudencia
  consultable por sí mismo.
- Una resolución vinculada con sentido ``estimado`` genera un evento
  ``recurso`` en ``contrato_eventos``, visible en la línea de tiempo.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

from db.connection import now_utc_iso
from db.database import connect, connect_read
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger
from services.dedupe import natural_expediente, normalize_organo

log = get_logger(__name__)

SENTIDOS_VALIDOS = ("estimado", "desestimado", "inadmitido", "desistimiento")


@dataclass
class Resolucion:
    numero_resolucion: str
    tribunal: str = "tacrc"
    numero_recurso: str | None = None
    fecha: str | None = None
    expediente: str | None = None
    organo: str | None = None
    sentido: str | None = None  # estimado|desestimado|inadmitido|desistimiento
    url_pdf: str | None = None
    resumen: str | None = None
    licitacion_id: str | None = None


_RES_KEYS = tuple(f.name for f in fields(Resolucion))


def upsert_resoluciones(items: list[Resolucion]) -> tuple[int, int]:
    """Inserta o actualiza resoluciones. Devuelve (nuevas, actualizadas).

    Idempotente: re-ejecutar con los mismos datos no duplica (invariante §3.2).
    El UPDATE no pisa ``licitacion_id`` ya asignado por la vinculación.
    """
    if not items:
        return 0, 0
    nuevas = actualizadas = 0
    with connect() as c:
        for res in items:
            existing = c.execute(
                "SELECT id FROM resoluciones_recurso "
                "WHERE tribunal = ? AND numero_resolucion = ?",
                (res.tribunal, res.numero_resolucion),
            ).fetchone()
            values = asdict(res)
            if existing:
                c.execute(
                    "UPDATE resoluciones_recurso SET numero_recurso = ?, fecha = ?, "
                    "expediente = ?, organo = ?, sentido = ?, url_pdf = ?, resumen = ?, "
                    "licitacion_id = COALESCE(licitacion_id, ?), fecha_extraccion = ? "
                    "WHERE id = ?",
                    (
                        values["numero_recurso"],
                        values["fecha"],
                        values["expediente"],
                        values["organo"],
                        values["sentido"],
                        values["url_pdf"],
                        values["resumen"],
                        values["licitacion_id"],
                        now_utc_iso(),
                        existing[0],
                    ),
                )
                actualizadas += 1
            else:
                cols = ", ".join(_RES_KEYS)
                placeholders = ", ".join("?" for _ in _RES_KEYS)
                c.execute(
                    # S608: cols/placeholders derivan del dataclass fijo Resolucion
                    f"INSERT INTO resoluciones_recurso ({cols}, fecha_extraccion) "  # noqa: S608
                    f"VALUES ({placeholders}, ?)",
                    [values[k] for k in _RES_KEYS] + [now_utc_iso()],
                )
                nuevas += 1
    return nuevas, actualizadas


def _registrar_evento_recurso(c: Any, licitacion_id: str, res: dict[str, Any]) -> bool:
    """Evento ``recurso`` en la línea de tiempo (solo resoluciones estimatorias)."""
    detalle = (
        f"Resolución {res['tribunal'].upper()} {res['numero_resolucion']} "
        f"({res['sentido']})"
    )
    ya_existe = c.execute(
        "SELECT 1 FROM contrato_eventos "
        "WHERE licitacion_id = ? AND tipo = 'recurso' AND detalle = ?",
        (licitacion_id, detalle),
    ).fetchone()
    if ya_existe:
        return False
    c.execute(
        "INSERT INTO contrato_eventos (licitacion_id, tipo, fecha, campo, detalle) "
        "VALUES (?, 'recurso', ?, 'resolucion', ?)",
        (licitacion_id, str(res.get("fecha") or now_utc_iso())[:10], detalle),
    )
    return True


def link_unlinked() -> dict[str, int]:
    """Vincula resoluciones sin ``licitacion_id`` por expediente + órgano.

    Matching débil: el expediente de la resolución debe coincidir con el
    expediente nacional de una licitación (id natural sin namespace). Si la
    resolución trae órgano, además debe coincidir normalizado; sin órgano se
    exige que el expediente sea unívoco. Devuelve contadores.
    """
    stats = {"vinculadas": 0, "eventos": 0}
    with connect() as c:
        pendientes = rows_to_dicts(
            c.execute(
                "SELECT id, tribunal, numero_resolucion, fecha, expediente, organo, sentido "
                "FROM resoluciones_recurso "
                "WHERE licitacion_id IS NULL AND expediente IS NOT NULL"
            )
        )
        if not pendientes:
            return stats
        licitaciones = rows_to_dicts(
            c.execute("SELECT id_externo, organo_contratacion FROM licitaciones")
        )
        por_expediente: dict[str, list[dict[str, Any]]] = {}
        for lic in licitaciones:
            por_expediente.setdefault(natural_expediente(lic["id_externo"]), []).append(lic)

        for res in pendientes:
            candidatas = por_expediente.get(str(res["expediente"]).strip(), [])
            organo_res = normalize_organo(res.get("organo"))
            if organo_res:
                matches = [
                    lic
                    for lic in candidatas
                    if normalize_organo(lic.get("organo_contratacion")) == organo_res
                ]
            else:
                matches = candidatas if len(candidatas) == 1 else []
            if len(matches) != 1:
                continue
            licitacion_id = matches[0]["id_externo"]
            c.execute(
                "UPDATE resoluciones_recurso SET licitacion_id = ? WHERE id = ?",
                (licitacion_id, res["id"]),
            )
            stats["vinculadas"] += 1
            if res.get("sentido") == "estimado" and _registrar_evento_recurso(
                c, licitacion_id, res
            ):
                stats["eventos"] += 1
    if stats["vinculadas"]:
        log.info("resoluciones_linked", **stats)
    return stats


def resoluciones(
    *,
    organo: str | None = None,
    sentido: str | None = None,
    desde: str | None = None,
    licitacion_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Listado filtrable de resoluciones (feed de jurisprudencia + detail panel)."""
    sql = (
        "SELECT r.id, r.tribunal, r.numero_resolucion, r.numero_recurso, r.fecha, "
        "       r.expediente, r.organo, r.sentido, r.url_pdf, r.resumen, "
        "       r.licitacion_id, l.titulo AS licitacion_titulo "
        "FROM resoluciones_recurso r "
        "LEFT JOIN licitaciones l ON l.id_externo = r.licitacion_id "
        "WHERE 1=1"
    )
    params: list[Any] = []
    if organo:
        sql += " AND r.organo LIKE ?"
        params.append(f"%{organo}%")
    if sentido:
        sql += " AND r.sentido = ?"
        params.append(sentido)
    if desde:
        sql += " AND r.fecha >= ?"
        params.append(desde)
    if licitacion_id:
        sql += " AND r.licitacion_id = ?"
        params.append(licitacion_id)
    sql += " ORDER BY r.fecha DESC, r.numero_resolucion DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))
