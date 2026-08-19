"""Dedupe cross-fuente de licitaciones (Fase 5.2, RFC 20260611-1).

Con varias fuentes (PLACSP, TED, PSCP) el mismo contrato puede entrar dos
veces — los órganos catalanes publican en PSCP y una parte llega también a
PLACSP. Sin dedupe, las métricas competitivas (cuota, HHI, renovaciones)
contarían el contrato duplicado.

Estrategia: **marcado reversible, nunca merge físico**. Las filas duplicadas
se registran en ``licitaciones_duplicados`` apuntando a su canónica y las
consultas analíticas las excluyen vía :func:`exclude_duplicados_sql`.

Clave débil de matching: órgano normalizado (lower, sin acentos, sin formas
societarias) + expediente nacional (el id natural sin namespace de fuente) +
CPV a 4 dígitos.

- Match completo (órgano + expediente + CPV4) → confianza 1.0, ``confirmed``.
- Órgano + expediente sin CPV coincidente → confianza 0.8, ``pending``
  (cola de revisión humana, mismo patrón que ``empresa_review_queue``;
  el status vive en la propia tabla, preferencia del RFC).

Canónico: la fila PLACSP cuando existe (más detalle de adjudicación);
si no, la más antigua por fecha de publicación/extracción.

La detección es incremental: cursor por fuente en ``ingestion_cursors``
(``dedupe_<fuente>``, watermark = max ``fecha_extraccion`` procesada), solo
evalúa filas nuevas de la pasada — sin full scan de pares.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from db.database import connect, connect_read, get_cursor, set_cursor
from db.repositories.base import rows_to_dicts

# Reexport: el fragmento SQL bajó a ``db/sql_fragments.py`` (ADR-022) para que
# ``db/`` pueda interpolarlo sin importar hacia arriba (ADR-024). La lógica de
# dominio del dedupe —matching, marcado, cursor— se queda aquí. Los call-sites
# de ``services/`` siguen importándolo de este módulo, así que el guardrail
# textual de ``tests/test_dedup_guardrail.py`` sigue viendo lo que vigila.
from db.sql_fragments import exclude_duplicados_sql as exclude_duplicados_sql
from observability.logging import get_logger
from observability.runtime_metrics import dedupe_marked_total, dedupe_match_rate
from services.normalization import normalize_company

log = get_logger(__name__)

CONFIANZA_EXACTA = 1.0
CONFIANZA_REVISION = 0.8


def normalize_organo(name: str | None) -> str | None:
    """Órgano plegado para matching: sin acentos, sin formas societarias, lower."""
    normalized = normalize_company(name)
    return normalized.lower() if normalized else None


def natural_expediente(id_externo: str) -> str:
    """Expediente nacional: el id natural sin el namespace de fuente (ADR-009)."""
    _, sep, rest = id_externo.partition(":")
    return rest if sep else id_externo


def _cpv4(cpv: str | None) -> str | None:
    if not cpv:
        return None
    digits = cpv.strip()[:4]
    return digits if len(digits) == 4 and digits.isdigit() else None


def match_key(organo: str | None, expediente: str, cpv: str | None) -> str | None:
    """Clave débil de matching; None si faltan órgano o expediente."""
    organo_norm = normalize_organo(organo)
    if not organo_norm or not expediente:
        return None
    return f"{organo_norm}|{expediente}|{_cpv4(cpv) or ''}"


@dataclass
class DedupeResult:
    fuente: str
    evaluadas: int = 0
    confirmados: int = 0
    pendientes: int = 0
    detalles: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, int | str]:
        return {
            "fuente": self.fuente,
            "evaluadas": self.evaluadas,
            "confirmados": self.confirmados,
            "pendientes": self.pendientes,
        }


def _pick_canonical(a: dict[str, Any], b: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """(canónica, duplicada): PLACSP gana; si no, la fila más antigua."""
    for row, other in ((a, b), (b, a)):
        if row["fuente"] == "placsp" and other["fuente"] != "placsp":
            return row, other
    key_a = (a.get("fecha_publicacion") or "9999", a.get("fecha_extraccion") or "9999")
    key_b = (b.get("fecha_publicacion") or "9999", b.get("fecha_extraccion") or "9999")
    return (a, b) if key_a <= key_b else (b, a)


def detect_duplicates(*, fuente: str) -> DedupeResult:
    """Detecta duplicados cross-fuente entre las filas nuevas de ``fuente``.

    Pensado para engancharse en ``_post_ingestion`` del runner de conectores
    (fail-open en el llamador) o ejecutarse manualmente tras un backfill.
    """
    result = DedupeResult(fuente=fuente)
    cursor_source = f"dedupe_{fuente}"
    watermark = str((get_cursor(cursor_source) or {}).get("last_seen_updated") or "")

    with connect_read() as c:
        nuevas = rows_to_dicts(
            c.execute(
                "SELECT id_externo, organo_contratacion, cpv, fuente, "
                "       fecha_publicacion, fecha_extraccion "
                "FROM licitaciones WHERE fuente = %s AND fecha_extraccion > %s",
                (fuente, watermark),
            )
        )
        if not nuevas:
            return result
        # Índice expediente → filas del resto de fuentes. Un solo SELECT de
        # columnas ligeras por pasada; el coste por fila nueva es O(1).
        otras = rows_to_dicts(
            c.execute(
                "SELECT id_externo, organo_contratacion, cpv, fuente, "
                "       fecha_publicacion, fecha_extraccion "
                "FROM licitaciones WHERE fuente != %s",
                (fuente,),
            )
        )
    por_expediente: dict[str, list[dict[str, Any]]] = {}
    for row in otras:
        por_expediente.setdefault(natural_expediente(row["id_externo"]), []).append(row)

    marcas: list[tuple[str, str, str, float, str]] = []
    max_extraccion = watermark
    for row in nuevas:
        result.evaluadas += 1
        if (row.get("fecha_extraccion") or "") > max_extraccion:
            max_extraccion = str(row["fecha_extraccion"])
        expediente = natural_expediente(row["id_externo"])
        organo_norm = normalize_organo(row.get("organo_contratacion"))
        if not expediente or not organo_norm:
            continue
        for candidata in por_expediente.get(expediente, []):
            if normalize_organo(candidata.get("organo_contratacion")) != organo_norm:
                continue
            cpv_row, cpv_cand = _cpv4(row.get("cpv")), _cpv4(candidata.get("cpv"))
            if cpv_row and cpv_cand and cpv_row == cpv_cand:
                confianza, status = CONFIANZA_EXACTA, "confirmed"
            else:
                confianza, status = CONFIANZA_REVISION, "pending"
            canonica, duplicada = _pick_canonical(row, candidata)
            clave = match_key(row.get("organo_contratacion"), expediente, row.get("cpv")) or ""
            marcas.append(
                (duplicada["id_externo"], canonica["id_externo"], clave, confianza, status)
            )
            source_pair = "|".join(sorted((str(row["fuente"]), str(candidata["fuente"]))))
            dedupe_marked_total.labels(source_pair=source_pair, status=status).inc()
            if status == "confirmed":
                result.confirmados += 1
            else:
                result.pendientes += 1
            result.detalles.append(
                {
                    "duplicada": duplicada["id_externo"],
                    "canonica": canonica["id_externo"],
                    "confianza": confianza,
                    "status": status,
                }
            )

    if marcas:
        with connect() as c:
            c.executemany(
                "INSERT INTO licitaciones_duplicados "
                "(licitacion_id, canonical_id, clave_match, confianza, status) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT(licitacion_id) DO NOTHING",
                marcas,
            )
    if max_extraccion and max_extraccion != watermark:
        set_cursor(cursor_source, last_seen_updated=max_extraccion)
    if result.evaluadas:
        # Solo se actualiza cuando hubo filas nuevas: una pasada vacía no debe
        # arrastrar el gauge a 0 y disparar la alerta de banda en falso.
        rate = (result.confirmados + result.pendientes) / result.evaluadas
        dedupe_match_rate.labels(fuente=fuente).set(rate)
    if result.confirmados or result.pendientes:
        log.info("dedupe_detected", **result.as_dict())
    return result


def review_pending(limit: int = 100) -> list[dict[str, Any]]:
    """Cola de revisión humana: matches con confianza < 1.0 sin resolver."""
    with connect_read() as c:
        return rows_to_dicts(
            c.execute(
                """
                SELECT d.licitacion_id, d.canonical_id, d.clave_match, d.confianza,
                       d.detectado_en, l.titulo, l.fuente,
                       lc.titulo AS titulo_canonica, lc.fuente AS fuente_canonica
                FROM licitaciones_duplicados d
                JOIN licitaciones l  ON l.id_externo  = d.licitacion_id
                JOIN licitaciones lc ON lc.id_externo = d.canonical_id
                WHERE d.status = 'pending'
                ORDER BY d.detectado_en LIMIT %s
                """,
                (max(1, min(int(limit), 500)),),
            )
        )


def resolve_pending(licitacion_id: str, *, accept: bool, resolved_by: str = "") -> bool:
    """Resuelve un match pendiente: aceptar lo confirma, rechazarlo lo descarta."""
    # resolved_at es TEXT (v39_licitaciones_duplicados) — castear explícitamente
    # evita el error de asignación timestamp→text.
    resolved_at_sql = "NOW()::text"
    with connect() as c:
        cur = c.execute(
            "UPDATE licitaciones_duplicados "  # noqa: S608 — resolved_at_sql es un fragmento constante
            f"SET status = %s, resolved_at = {resolved_at_sql}, resolved_by = %s "
            "WHERE licitacion_id = %s AND status = 'pending'",
            ("confirmed" if accept else "rejected", resolved_by, licitacion_id),
        )
        return bool(cur.rowcount)


def medir_solape(fuente_a: str = "pscp", fuente_b: str = "placsp") -> dict[str, Any]:
    """Mide el solape detectado entre dos fuentes (acceptance del RFC)."""
    with connect_read() as c:
        total_a = c.execute(
            "SELECT COUNT(*) FROM licitaciones WHERE fuente = %s", (fuente_a,)
        ).fetchone()[0]
        solapadas = c.execute(
            """
            SELECT COUNT(*) FROM licitaciones_duplicados d
            JOIN licitaciones l  ON l.id_externo  = d.licitacion_id
            JOIN licitaciones lc ON lc.id_externo = d.canonical_id
            WHERE d.status != 'rejected'
              AND ((l.fuente = %s AND lc.fuente = %s) OR (l.fuente = %s AND lc.fuente = %s))
            """,
            (fuente_a, fuente_b, fuente_b, fuente_a),
        ).fetchone()[0]
    pct = round(solapadas * 100.0 / total_a, 2) if total_a else 0.0
    return {"fuente": fuente_a, "total": total_a, "solapadas": solapadas, "solape_pct": pct}
