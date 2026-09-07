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

**Alertas de expediente seguido (S4.5).** El mismo recorrido emite además un
evento ``licitacion.cambiada`` en el outbox cuando el expediente que cambió lo
sigue alguien: está en los favoritos de un usuario o es una oportunidad abierta
de alguna organización. Se hace aquí, dentro de ``derive_new_events``, y no en
un productor aparte, por dos razones que son la misma: este bucle **ya** tiene
el cursor de ``ingestion_cursors`` que evita releer el historial entero, y
**ya** compara antes/después con ``values_equal``, que es lo que impide que una
re-ingesta sin cambio real genere un aviso. Un segundo productor habría tenido
que duplicar las dos cosas y habrían divergido.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from db.database import connect, connect_read, get_cursor, set_cursor
from db.events import append_domain_event, seguidores_de_licitacion
from db.repositories.aggregates import LicitacionesFilters, build_licitaciones_where
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger
from shared.numeric import values_equal

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

#: Campos cuyo cambio se avisa a quien sigue el expediente (S4.5).
#:
#: Es un superconjunto de :data:`_CAMPOS_EVENTO` con ``fecha_limite``, ``cpv``
#: y ``url``: al seguidor de un expediente le importa sobre todo que le hayan
#: movido el plazo, que es justo el campo que NO genera evento de contrato
#: (mover el plazo no modifica el contrato, modifica la oportunidad). Siguen
#: fuera ``titulo`` y ``descripcion`` por lo mismo que arriba — un retoque de
#: redacción no es una novedad.
_CAMPOS_SEGUIDOS = (
    "estado",
    "importe",
    "fecha_limite",
    "fecha_fin",
    "duracion_valor",
    "duracion_unidad",
    "cpv",
    "url",
)

#: Columnas de la fila actual que hacen de estado «después» del último cambio.
_COLS_ESTADO_ACTUAL = (
    "estado",
    "importe",
    "fecha_fin",
    "duracion_valor",
    "duracion_unidad",
    "fecha_limite",
    "cpv",
    "url",
    "titulo",
)


def _emitir_cambio_seguido(
    conn: Any,
    *,
    id_externo: str,
    history_id: int,
    antes: dict[str, Any],
    despues: dict[str, Any],
    changed: list[str],
) -> bool:
    """Escribe ``licitacion.cambiada`` si el expediente lo sigue alguien.

    Devuelve ``True`` si emitió. Tres cortes, y los tres importan:

    1. Sin campos con cambio **real** (``values_equal``), no hay evento: una
       re-ingesta que reescribe los mismos valores no despierta a nadie.
    2. Sin seguidores, no hay evento. La consulta es lo último que se hace, no
       lo primero, porque el 99% de las filas de historial son de expedientes
       que no sigue nadie y descartarlas por los campos es más barato.
    3. El evento va en la transacción del cursor (``conn``): si la pasada se
       revierte, el aviso se va con ella. Es el outbox, no un efecto lateral.
    """
    valores: dict[str, dict[str, Any]] = {}
    for campo in changed:
        if campo not in _CAMPOS_SEGUIDOS:
            continue
        valor_antes = antes.get(campo)
        valor_despues = despues.get(campo)
        if values_equal(valor_antes, valor_despues):
            continue
        valores[campo] = {"antes": valor_antes, "despues": valor_despues}
    if not valores:
        return False

    seguidores = seguidores_de_licitacion(id_externo)
    if not seguidores:
        return False

    from db.users import get_user_by_id
    from shared.identity import user_key_from_email

    resueltos: list[dict[str, Any]] = []
    vistos: set[tuple[str, int]] = set()
    for fila in seguidores:
        organization_id = int(fila.get("organization_id") or 0)
        if not organization_id:
            continue
        user_key = fila.get("user_key")
        if not user_key:
            bruto = fila.get("user_id")
            if bruto is None:
                continue
            user_id = int(bruto)
            usuario = get_user_by_id(user_id)
            if usuario is None:
                continue
            user_key = user_key_from_email(usuario.get("email"), user_id)
        clave = (str(user_key), organization_id)
        if clave in vistos:
            continue
        vistos.add(clave)
        resueltos.append({"user_key": str(user_key), "organization_id": organization_id})

    if not resueltos:
        return False

    append_domain_event(
        "licitacion.cambiada",
        id_externo,
        "licitacion",
        {
            "id_externo": id_externo,
            "licitacion_id": id_externo,
            "titulo": despues.get("titulo") or antes.get("titulo"),
            "changed_fields": sorted(valores),
            "valores": valores,
            "history_id": history_id,
            "seguidores": resueltos,
        },
        conn=conn,
    )
    return True


def _classify(campo: str, antes: Any, despues: Any) -> tuple[str, float | None, str] | None:
    """Devuelve (tipo, importe_delta, detalle) o None si el cambio no es evento."""
    # Con tolerancia y no `==`: `importe` es `real` en producción y el snapshot
    # de historial puede diferir del valor actual sólo por el redondeo a
    # float4, sin que nadie haya modificado el contrato. Esto además protege
    # de las filas de historial basura escritas antes del fix en db/upsert.py
    # (ver shared/numeric.py): siguen en la tabla y el cursor las procesará.
    if values_equal(antes, despues):
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
                "FROM licitaciones_history WHERE id > %s ORDER BY id LIMIT %s",
                (last_id, batch_size),
            )
        )
        if not rows:
            return 0

        inserted = 0
        avisados = 0
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
                # La proyección incluye `fecha_limite`, `cpv`, `url` y `titulo`
                # además de los cinco campos de contrato: el aviso al seguidor
                # (S4.5) los necesita para decir qué cambió y a qué.
                cur_row = c.execute(
                    "SELECT " + ", ".join(_COLS_ESTADO_ACTUAL) + " "
                    "FROM licitaciones WHERE id_externo = %s",
                    (row["id_externo"],),
                ).fetchone()
                if cur_row is None:
                    continue
                despues_state = dict(zip(_COLS_ESTADO_ACTUAL, cur_row, strict=False))

            changed = [f.strip() for f in (row["changed_fields"] or "").split(",")]
            if _emitir_cambio_seguido(
                c,
                id_externo=str(row["id_externo"]),
                history_id=int(row["id"]),
                antes=snapshot,
                despues=despues_state,
                changed=changed,
            ):
                avisados += 1
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
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
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
    if inserted or avisados:
        log.info(
            "contract_events_derived",
            inserted=inserted,
            cambios_seguidos=avisados,
            hasta_history_id=max_id,
        )
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
                FROM contrato_eventos WHERE licitacion_id = %s
                UNION ALL
                SELECT substr(l.fecha_publicacion, 1, 10), 'publicacion',
                       NULL, NULL, NULL, NULL, l.titulo
                FROM licitaciones l
                WHERE l.id_externo = %s AND l.fecha_publicacion IS NOT NULL
                UNION ALL
                SELECT substr(a.fecha_adjudicacion, 1, 10), 'adjudicacion',
                       'adjudicatario', NULL, COALESCE(e.nombre_canonico, a.nombre),
                       a.importe_adjudicado,
                       'adjudicado a ' || COALESCE(e.nombre_canonico, a.nombre)
                FROM adjudicaciones a
                LEFT JOIN empresas e ON e.empresa_id = a.empresa_id
                WHERE a.licitacion_id = %s AND a.fecha_adjudicacion IS NOT NULL
                ORDER BY 1
                """,
                (licitacion_id, licitacion_id, licitacion_id),
            )
        )
    return eventos


def eventos_recientes(
    *,
    tipos: tuple[str, ...] | None = None,
    dias: int = 30,
    limit: int = 100,
    desde: str | None = None,
    hasta: str | None = None,
    filters: LicitacionesFilters | None = None,
) -> list[dict[str, Any]]:
    """Feed de eventos recientes (modificaciones, prórrogas…) para el dashboard.

    ``filters`` acota el feed al mismo universo de licitaciones que el resto del
    Resumen (CCAA, tecnología, estado, importe mínimo, búsqueda…): el JOIN con
    ``licitaciones`` ya estaba ahí para el título, así que el ámbito se aplica
    sobre él con el mismo ``WHERE`` que las agregaciones.

    Las fechas van aparte a propósito y **no** dentro de ``filters``: ahí
    acotarían ``fecha_publicacion`` (cuándo se publicó el expediente) y aquí lo
    que se pregunta es cuándo se movió el contrato. ``desde`` sustituye a la
    ventana relativa de ``dias``; ``hasta`` la remata por arriba.
    """
    cutoff_expr = "to_char(CURRENT_DATE - (%s * INTERVAL '1 day'), 'YYYY-MM-DD')"
    clauses: list[str] = []
    params: list[Any] = []
    if desde:
        clauses.append("ev.fecha >= %s")
        params.append(desde)
    else:
        # cutoff_expr es un fragmento constante; el valor va con placeholder
        clauses.append(f"ev.fecha >= {cutoff_expr}")
        params.append(max(1, int(dias)))
    if hasta:
        clauses.append("ev.fecha <= %s")
        params.append(hasta)
    if tipos:
        placeholders = ",".join("%s" for _ in tipos)
        clauses.append(f"ev.tipo IN ({placeholders})")
        params.extend(tipos)
    if filters is not None and not filters.is_empty():
        lic_where, lic_params = build_licitaciones_where(filters, alias="l")
        clauses.append(f"({lic_where})")
        params.extend(lic_params)

    # Lo único interpolado son fragmentos construidos aquí o en
    # `build_licitaciones_where`; todo valor de usuario va con placeholder.
    sql = (
        "SELECT ev.licitacion_id, ev.tipo, ev.fecha, ev.detalle, ev.importe_delta, "
        "       l.titulo, l.organo_contratacion, l.fuente "
        "FROM contrato_eventos ev "
        "JOIN licitaciones l ON l.id_externo = ev.licitacion_id "
        "WHERE " + " AND ".join(clauses) + " ORDER BY ev.fecha DESC LIMIT %s"
    )
    params.append(max(1, min(int(limit), 500)))
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))
