"""SQL de la limpieza del ruido de float4 en ``licitaciones_history`` (Postgres).

``db.historial_ruido.candidatos_ruido_importe`` lee el importe de antes del
snapshot de la fila y el de después del snapshot siguiente o de la fila actual;
``borrar_ruido_importe`` borra las filas y sus eventos de importe. La decisión
de qué es ruido se prueba sin BD en ``tests/test_unit_ruido_importe.py``.
"""

from __future__ import annotations

import json
from typing import Any

_A = "ted:ruido-a"
_B = "ted:ruido-b"
_C = "ted:ruido-c"


def _snapshot(id_externo: str, importe: float | None, descripcion: str = "d") -> str:
    # Mismo orden de claves que `db/upsert.py::_HISTORY_SELECT_COLS`.
    return json.dumps(
        {
            "id_externo": id_externo,
            "titulo": "t",
            "descripcion": descripcion,
            "organo_contratacion": "o",
            "importe": importe,
            "estado": "PUB",
        },
        ensure_ascii=False,
    )


def _historial(c: Any, id_externo: str, snapshot: str, cambiados: str) -> int:
    return int(
        c.execute(
            "INSERT INTO licitaciones_history "
            "(id_externo, captured_at, source, snapshot_json, changed_fields) "
            "VALUES (%s, '2026-08-10T10:00:00+00:00', 'ted', %s, %s) RETURNING id",
            (id_externo, snapshot, cambiados),
        ).fetchone()[0]
    )


def _evento(c: Any, history_id: int, id_externo: str, tipo: str, campo: str) -> None:
    c.execute(
        "INSERT INTO contrato_eventos (licitacion_id, tipo, fecha, campo, history_id) "
        "VALUES (%s, %s, '2026-08-10', %s, %s)",
        (id_externo, tipo, campo, history_id),
    )


def _sembrar(c: Any) -> dict[str, int]:
    # Importe actual tal como lo dejó v156: el float4 convertido a double.
    for id_externo, importe in ((_A, 12345.669921875), (_B, 200.0), (_C, 50.0)):
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion, importe) "
            "VALUES (%s, 't', 'ted', '2026-08-10T10:00:00+00:00', %s)",
            (id_externo, importe),
        )
    ids = {
        "a1": _historial(c, _A, _snapshot(_A, 12345.67), "importe"),
        # Un texto que cita la clave no debe leerse como el importe.
        "a2": _historial(c, _A, _snapshot(_A, 12345.67, 'dice "importe": 1'), "estado"),
        "a3": _historial(c, _A, _snapshot(_A, 12345.67), "importe"),
        "b1": _historial(c, _B, _snapshot(_B, 100.0), "importe"),
        # Truncado antes de llegar al importe, como hace el upsert pasados 50 000.
        "c1": _historial(c, _C, _snapshot(_C, 50.0)[:60] + "...(truncado)", "importe"),
    }
    _evento(c, ids["a1"], _A, "modificacion", "importe")
    _evento(c, ids["a2"], _A, "cambio_estado", "estado")
    _evento(c, ids["b1"], _B, "modificacion", "importe")
    return ids


def test_integration_candidatos_leen_antes_y_despues(tmp_db: Any) -> None:
    from db.database import connect
    from db.historial_ruido import candidatos_ruido_importe

    with connect() as c:
        ids = _sembrar(c)

    filas = {f["history_id"]: f for f in candidatos_ruido_importe(0, 100)}

    assert sorted(filas) == sorted([ids["a1"], ids["a3"], ids["b1"], ids["c1"]])
    # Después de a1 es el snapshot de a2 (no el texto de su descripción).
    assert (filas[ids["a1"]]["antes"], filas[ids["a1"]]["despues"]) == (12345.67, 12345.67)
    # La última fila toma el importe actual.
    assert filas[ids["a3"]]["despues"] == 12345.669921875
    assert (filas[ids["b1"]]["antes"], filas[ids["b1"]]["despues"]) == (100.0, 200.0)
    assert filas[ids["c1"]]["antes"] is None


def test_integration_candidatos_paginan_por_id(tmp_db: Any) -> None:
    from db.database import connect
    from db.historial_ruido import candidatos_ruido_importe

    with connect() as c:
        ids = _sembrar(c)

    lote = candidatos_ruido_importe(ids["a1"], 1)

    assert [f["history_id"] for f in lote] == [ids["a3"]]


def test_integration_borrar_quita_filas_y_eventos_de_importe(tmp_db: Any) -> None:
    from db.database import connect, connect_read
    from db.historial_ruido import borrar_ruido_importe

    with connect() as c:
        ids = _sembrar(c)

    # a2 tiene otro cambio: el DELETE no la toca aunque venga en la lista.
    assert borrar_ruido_importe([ids["a1"], ids["a3"], ids["a2"]]) == (1, 2)

    with connect_read() as c:
        quedan = sorted(r[0] for r in c.execute("SELECT id FROM licitaciones_history").fetchall())
        eventos = sorted(
            r[0] for r in c.execute("SELECT history_id FROM contrato_eventos").fetchall()
        )
    assert quedan == sorted([ids["a2"], ids["b1"], ids["c1"]])
    assert eventos == sorted([ids["a2"], ids["b1"]])
