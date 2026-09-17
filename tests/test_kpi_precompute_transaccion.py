"""El reemplazo de ``kpi_snapshots`` es atómico visto desde otra conexión.

``db.kpi_precompute.persist_snapshots`` borra la tabla entera y vuelve a
insertar el snapshot completo. El código confía en que el ``DELETE`` y el
``INSERT`` vayan en la misma transacción, la del ``connect()`` de
``compute_and_persist_snapshots``, para que eso no deje a nadie sin datos. No
lo hace evidente: bastaría un ``commit()`` tras el ``DELETE``, o sacar el
borrado a su propia conexión, para que el overview de
``db/repositories/kpi_snapshots.py`` encontrase la tabla vacía durante el
``INSERT`` —y volviese al cálculo en vivo— o para que un ``INSERT`` fallido la
dejase vacía hasta el ciclo siguiente.

Los tres tests ejecutan ``run_kpi_precompute`` contra Postgres:

- el primero comprueba la transacción compartida directamente, comparando
  ``pg_current_xact_id()`` en la conexión que ejecuta cada sentencia;
- los otros dos, sus dos consecuencias observables, leyendo con
  ``get_all_latest``, que abre su propia conexión: dentro de la conexión del
  job un borrado confirmado y uno pendiente se ven igual.

Hace falta el primero porque las consecuencias no bastan: un ``DELETE``
pendiente en una conexión y un ``INSERT`` confirmado antes en otra también
ocultan la tabla vacía y sobreviven a un ``INSERT`` fallido.

Qué **no** fijan: que el cálculo comparta conexión con el reemplazo. Con el
aislamiento por defecto (``READ COMMITTED``) calcular en otra conexión antes de
reemplazar deja la tabla igual, y ningún lector lo distingue.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

_COMPUTED_AT_ANTERIOR = "2020-01-01T00:00:00+00:00"

#: Lo que ``get_all_latest`` devuelve mientras el snapshot sembrado es el vigente.
_SNAPSHOT_ANTERIOR: dict[str, Any] = {
    "_computed_at": _COMPUTED_AT_ANTERIOR,
    "anterior_a": 1,
    "anterior_b": 2,
}


def _siembra_snapshot_anterior(db_mod: Any) -> None:
    """Deja confirmado un snapshot de dos métricas que el job tiene que reemplazar."""
    from db.kpi_precompute import persist_snapshots

    filas = [
        {
            "metrica": metrica,
            "dimension": "global",
            "valor": valor,
            "valor_text": None,
            "computed_at": _COMPUTED_AT_ANTERIOR,
        }
        for metrica, valor in (("anterior_a", 1), ("anterior_b", 2))
    ]
    with db_mod.connect() as c:
        persist_snapshots(c, filas)


def test_el_delete_y_el_insert_comparten_transaccion(tmp_db, monkeypatch):
    """El ``DELETE`` y el ``INSERT`` del reemplazo se ejecutan con el mismo ``pg_current_xact_id()``.

    Se interceptan ``execute`` y ``executemany`` del adaptador de conexión:
    tras cada sentencia sobre ``kpi_snapshots`` se pregunta a esa misma
    conexión, con un cursor aparte, en qué transacción está. Un ``commit()``
    entre las dos, o cada una en su conexión, da dos identificadores.
    """
    db_mod, _ = tmp_db
    _siembra_snapshot_anterior(db_mod)

    from db.connection import _PgConnAdapter
    from scheduler.kpi_precompute import run_kpi_precompute

    xact_del_delete: list[str] = []
    xact_del_insert: list[str] = []
    execute_real = _PgConnAdapter.execute
    executemany_real = _PgConnAdapter.executemany

    def _xact_actual(adaptador: _PgConnAdapter) -> str:
        with adaptador._conn.cursor() as cur:
            cur.execute("SELECT pg_current_xact_id()::text")
            return str(cur.fetchone()[0])

    def execute_anotando(self: _PgConnAdapter, sql: str, params: Any = None) -> _PgConnAdapter:
        resultado = execute_real(self, sql, params)
        if sql.startswith("DELETE FROM kpi_snapshots"):
            xact_del_delete.append(_xact_actual(self))
        return resultado

    def executemany_anotando(self: _PgConnAdapter, sql: str, seq: Any) -> None:
        executemany_real(self, sql, seq)
        if sql.startswith("INSERT INTO kpi_snapshots"):
            xact_del_insert.append(_xact_actual(self))

    monkeypatch.setattr(_PgConnAdapter, "execute", execute_anotando)
    monkeypatch.setattr(_PgConnAdapter, "executemany", executemany_anotando)

    run_kpi_precompute()

    assert len(xact_del_insert) == 1
    assert xact_del_delete == xact_del_insert


def test_otra_conexion_sigue_viendo_el_snapshot_anterior_durante_el_insert(tmp_db, monkeypatch):
    """Con el ``DELETE`` ya ejecutado y antes del ``INSERT``, fuera se ve el snapshot anterior.

    Se intercepta ``executemany`` del adaptador de conexión solo para mirar:
    cuando va a insertar en ``kpi_snapshots`` lee la tabla desde otra conexión
    y después llama al original. Al acabar el job, fuera ya solo se ve el
    snapshot nuevo.
    """
    db_mod, _ = tmp_db
    _siembra_snapshot_anterior(db_mod)

    from db.connection import _PgConnAdapter
    from db.kpi_precompute import get_all_latest
    from scheduler.kpi_precompute import run_kpi_precompute

    vistas_durante_el_insert: list[dict[str, Any]] = []
    executemany_real = _PgConnAdapter.executemany

    def mirando_antes(self: _PgConnAdapter, sql: str, seq: Any) -> None:
        if sql.startswith("INSERT INTO kpi_snapshots"):
            vistas_durante_el_insert.append(get_all_latest())
        executemany_real(self, sql, seq)

    monkeypatch.setattr(_PgConnAdapter, "executemany", mirando_antes)

    run_kpi_precompute()

    assert vistas_durante_el_insert == [_SNAPSHOT_ANTERIOR]
    despues = get_all_latest()
    assert "anterior_a" not in despues
    assert "anterior_b" not in despues
    assert "total_licitaciones" in despues


def test_si_postgres_rechaza_el_insert_queda_el_snapshot_anterior(tmp_db, monkeypatch):
    """Un ``INSERT`` rechazado deshace también el ``DELETE`` que lo precedió.

    Al cálculo real se le añade una fila con ``metrica`` nula, que Postgres
    rechaza por el ``NOT NULL`` de ``kpi_snapshots`` cuando el ``DELETE`` ya se
    ha ejecutado. El error llega al llamante y la tabla conserva el snapshot
    anterior, no queda vacía.
    """
    db_mod, _ = tmp_db
    _siembra_snapshot_anterior(db_mod)

    import db.kpi_precompute as kpi_db
    from scheduler.kpi_precompute import run_kpi_precompute

    calcular_real = kpi_db.compute_all_kpis

    def con_fila_invalida(conn: Any) -> list[dict[str, Any]]:
        filas = calcular_real(conn)
        return [*filas, {**filas[-1], "metrica": None}]

    monkeypatch.setattr(kpi_db, "compute_all_kpis", con_fila_invalida)

    with pytest.raises(psycopg.errors.NotNullViolation):
        run_kpi_precompute()

    assert kpi_db.get_all_latest() == _SNAPSHOT_ANTERIOR
