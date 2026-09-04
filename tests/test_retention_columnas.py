"""La política de retención se coteja contra el schema real.

``run_retention`` aísla cada tabla en su propio savepoint y anota ``-1`` si
falla, para que un problema con una no impida purgar las demás. El precio es
que un nombre de columna equivocado no rompe nada visible: la tabla
simplemente **nunca se purga**, y el error sale en cada pasada diaria mezclado
con el resto del log.

Pasó: hasta 2026-09 la regla de ``licitaciones_history`` apuntaba a
``changed_at`` y la columna se llama ``captured_at``. El fallo llevaba ahí
desde que existe la tabla y se descubrió de rebote, leyendo el log de una
pasada por otro motivo.

Este test es la costura que faltaba entre la política y el schema, del mismo
tipo que ``test_retention_solicitudes.py`` entre el job y el aviso legal.
"""

from __future__ import annotations

import pytest

from scheduler.retention import COLUMNA_FECHA


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def test_toda_columna_de_la_politica_existe_en_el_schema(db) -> None:
    from db.database import connect

    with connect() as c:
        filas = c.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema()"
        ).fetchall()
    reales = {(str(t), str(col)) for t, col in filas}

    faltan = [
        f"{tabla}.{columna}"
        for tabla, columna in COLUMNA_FECHA.items()
        if (tabla, columna) not in reales
    ]
    assert not faltan, (
        f"La política de retención purga por columnas que no existen: {faltan}. "
        "Esas tablas no se purgan y el error se traga por tabla."
    )


def test_la_politica_cubre_licitaciones_history_por_su_fecha_real() -> None:
    """El caso concreto que motivó el test, fijado para que no vuelva."""
    assert COLUMNA_FECHA["licitaciones_history"] == "captured_at"
