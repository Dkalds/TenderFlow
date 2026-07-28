"""Eventos de contrato derivados de ``licitaciones_history`` (Fase 4).

``licitaciones_history`` guarda, por cada cambio detectado en el upsert, un
snapshot del estado *anterior* y la lista ``changed_fields``. Este módulo
convierte esos diffs en eventos tipados del ciclo de vida del contrato:

- ``estado`` → ADJ: **adjudicacion** · RES: **formalizacion** ·
  ANUL: **anulacion** · resto: **cambio_estado**
- ``importe`` → **modificacion** con ``importe_delta``
- ``fecha_fin`` / ``duracion_*`` → **prorroga** si extiende, **modificacion**
  si recorta

El valor "después" de un cambio es el snapshot del siguiente registro de
historial de la misma licitación (cada snapshot es el estado previo al
cambio siguiente) o, para el último cambio, la fila actual.

Incremental e idempotente: cursor en ``ingestion_cursors``
(source='contract_events', last_entry_id = último history_id procesado) +
índice único sobre (history_id, tipo, campo).

Nota: las renovaciones (Fase 2) no necesitan estos eventos para reflejar
prórrogas — la fila actual de licitaciones ya contiene la fecha_fin
extendida. Los eventos aportan el *cuándo y cuánto* del cambio.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from db.database import connect, connect_read, get_cursor, set_cursor
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# DTOs — respuesta tipada de GET /eventos (el feed reciente, no la timeline
# por licitación, que sigue siendo dict[str, Any] de forma variable por UNION).
# ---------------------------------------------------------------------------


class EventoFeedItem(BaseModel):
    """Un evento del feed reciente de movimientos de contrato."""

    licitacion_id: str
    tipo: str
    fecha: str | None = None
    detalle: str | None = None
    importe_delta: float | None = None
    titulo: str | None = None
    organo_contratacion: str | None = None
    fuente: str | None = None


class EventosFeedResult(BaseModel):
    """Respuesta de ``GET /eventos``."""

    items: list[EventoFeedItem] = []
    dias: int = 30


_CURSOR_SOURCE = "contract_events"

_ESTADO_EVENTO = {
    "ADJ": "adjudicacion",
    "ADJUDICADA": "adjudicacion",
    "RES": "formalizacion",
    "ANUL": "anulacion",
}

# Campos de historial que generan evento (titulo/descripcion son ruido editorial)
_CAMPOS_EVENTO = ("estado", "importe", "fecha_fin", "duracion_valor", "duracion_unidad")


def _classify(campo: str, antes: Any, despues: Any) -> tuple[str, float | None, str] | None:
    """Devuelve (tipo, importe_delta, detalle) o None si el cambio no es evento."""
    if antes == despues:
        return None
    if campo == "estado":
        tipo = _ESTADO_EVENTO.get(str(despues or "").upper(), "cambio_estado")
        return tipo, None, f"estado {antes or '—'} → {despues or '—'}"
    if campo == "importe":
        try:
            delta = float(despues) - float(antes)
        except (TypeError, ValueError):
            delta = None
        if not delta:
            return None
        return "modificacion", delta, f"importe {antes} → {despues}"
    if campo == "fecha_fin":
        if not despues:
            return None
        tipo = "prorroga" if not antes or str(despues) > str(antes) else "modificacion"
        return tipo, None, f"fecha_fin {antes or '—'} → {despues}"
    if campo in ("duracion_valor", "duracion_unidad"):
        if despues is None:
            return None
        if campo == "duracion_valor":
            try:
                extiende = antes is None or float(despues) > float(antes)
            except (TypeError, ValueError):
                extiende = False
            tipo = "prorroga" if extiende else "modificacion"
        else:
            tipo = "modificacion"
        return tipo, None, f"{campo} {antes or '—'} → {despues}"
    return None


def derive_new_events(batch_size: int = 1000) -> int:
    """Deriva eventos de las filas de historial aún no procesadas.

    Devuelve el número de eventos insertados. Pensado para ejecutarse tras
    cada ingesta (fail-open en los llamadores) o manualmente para backfill.
    """
    cursor = get_cursor(_CURSOR_SOURCE)
    last_id = int((cursor or {}).get("last_entry_id") or 0)

    with connect() as c:
        rows = rows_to_dicts(
            c.execute(
                "SELECT id, id_externo, captured_at, snapshot_json, changed_fields "
                "FROM licitaciones_history WHERE id > ? ORDER BY id LIMIT ?",
                (last_id, batch_size),
            )
        )
        if not rows:
            return 0

        inserted = 0
        max_id = last_id
        for i, row in enumerate(rows):
            max_id = max(max_id, int(row["id"]))
            try:
                snapshot = json.loads(row["snapshot_json"])
            except (TypeError, ValueError):
                continue

            # Estado "después": snapshot del siguiente cambio de la misma
            # licitación dentro del lote, o la fila actual de licitaciones.
            despues_state: dict[str, Any] | None = None
            for nxt in rows[i + 1 :]:
                if nxt["id_externo"] == row["id_externo"]:
                    try:
                        despues_state = json.loads(nxt["snapshot_json"])
                    except (TypeError, ValueError):
                        despues_state = None
                    break
            if despues_state is None:
                cur_row = c.execute(
                    "SELECT estado, importe, fecha_fin, duracion_valor, duracion_unidad "
                    "FROM licitaciones WHERE id_externo = ?",
                    (row["id_externo"],),
                ).fetchone()
                if cur_row is None:
                    continue
                despues_state = dict(
                    zip(
                        ("estado", "importe", "fecha_fin", "duracion_valor", "duracion_unidad"),
                        cur_row,
                        strict=False,
                    )
                )

            changed = [f.strip() for f in (row["changed_fields"] or "").split(",")]
            for campo in changed:
                if campo not in _CAMPOS_EVENTO:
                    continue
                evento = _classify(campo, snapshot.get(campo), despues_state.get(campo))
                if evento is None:
                    continue
                tipo, delta, detalle = evento
                c.execute(
                    "INSERT INTO contrato_eventos "
                    "(licitacion_id, tipo, fecha, campo, valor_antes, valor_despues, "
                    " importe_delta, detalle, history_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (history_id, tipo, COALESCE(campo, '')) "
                    "WHERE history_id IS NOT NULL DO NOTHING",
                    (
                        row["id_externo"],
                        tipo,
                        str(row["captured_at"])[:10],
                        campo,
                        str(snapshot.get(campo)) if snapshot.get(campo) is not None else None,
                        str(despues_state.get(campo))
                        if despues_state.get(campo) is not None
                        else None,
                        delta,
                        detalle,
                        int(row["id"]),
                    ),
                )
                inserted += 1

    set_cursor(_CURSOR_SOURCE, last_entry_id=str(max_id))
    if inserted:
        log.info("contract_events_derived", inserted=inserted, hasta_history_id=max_id)
    return inserted


def derive_all_events(batch_size: int = 1000) -> int:
    """Backfill: itera lotes hasta agotar el historial pendiente."""
    total = 0
    while True:
        n = derive_new_events(batch_size)
        if n == 0:
            cursor = get_cursor(_CURSOR_SOURCE)
            with connect_read() as c:
                max_hist = c.execute("SELECT COALESCE(MAX(id), 0) FROM licitaciones_history")
                max_hist_id = int(max_hist.fetchone()[0])
            if int((cursor or {}).get("last_entry_id") or 0) >= max_hist_id:
                break
        total += n
    return total


def timeline(licitacion_id: str) -> list[dict[str, Any]]:
    """Línea de tiempo completa de un contrato.

    Une los eventos materializados con los hitos implícitos en los datos:
    publicación (licitaciones.fecha_publicacion) y adjudicaciones por empresa
    (adjudicaciones.fecha_adjudicacion, con nombre canónico del maestro).
    """
    with connect_read() as c:
        eventos = rows_to_dicts(
            c.execute(
                """
                SELECT fecha, tipo, campo, valor_antes, valor_despues,
                       importe_delta, detalle
                FROM contrato_eventos WHERE licitacion_id = ?
                UNION ALL
                SELECT substr(l.fecha_publicacion, 1, 10), 'publicacion',
                       NULL, NULL, NULL, NULL, l.titulo
                FROM licitaciones l
                WHERE l.id_externo = ? AND l.fecha_publicacion IS NOT NULL
                UNION ALL
                SELECT substr(a.fecha_adjudicacion, 1, 10), 'adjudicacion',
                       'adjudicatario', NULL, COALESCE(e.nombre_canonico, a.nombre),
                       a.importe_adjudicado,
                       'adjudicado a ' || COALESCE(e.nombre_canonico, a.nombre)
                FROM adjudicaciones a
                LEFT JOIN empresas e ON e.empresa_id = a.empresa_id
                WHERE a.licitacion_id = ? AND a.fecha_adjudicacion IS NOT NULL
                ORDER BY 1
                """,
                (licitacion_id, licitacion_id, licitacion_id),
            )
        )
    return eventos


def eventos_recientes(
    *, tipos: tuple[str, ...] | None = None, dias: int = 30, limit: int = 100
) -> list[dict[str, Any]]:
    """Feed de eventos recientes (modificaciones, prórrogas…) para el dashboard."""
    cutoff_expr = "to_char(CURRENT_DATE - (? * INTERVAL '1 day'), 'YYYY-MM-DD')"
    sql = (
        "SELECT ev.licitacion_id, ev.tipo, ev.fecha, ev.detalle, ev.importe_delta, "  # noqa: S608
        "       l.titulo, l.organo_contratacion, l.fuente "
        "FROM contrato_eventos ev "
        "JOIN licitaciones l ON l.id_externo = ev.licitacion_id "
        f"WHERE ev.fecha >= {cutoff_expr}"  # cutoff_expr es un fragmento constante; valores con ?
    )
    params: list[Any] = [max(1, int(dias))]
    if tipos:
        placeholders = ",".join("?" for _ in tipos)
        sql += f" AND ev.tipo IN ({placeholders})"
        params.extend(tipos)
    sql += " ORDER BY ev.fecha DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))
