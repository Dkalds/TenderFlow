"""Regresiones unitarias de la revisión ``v110`` (pursuit por lote).

Las migraciones se aplican por subproceso (``alembic upgrade head`` en
``tests/conftest.py``), así que su código Python no se ejecuta nunca dentro de
la suite: ni se cubre ni se comprueba. Este módulo sigue el patrón de v52/v56/
v58/v59/v64/v76 —cargar el módulo y llamar a ``upgrade()``/``downgrade()`` con
un ``op`` de mentira— para fijar lo que la tabla debe ser antes de que exista
en ninguna base real.

Lo que se afirma aquí es exactamente lo que puede romper producción:

- que las dos columnas nuevas son NULLables y sin DEFAULT (metadata-only), que
  es lo que garantiza que **las filas existentes no cambian**;
- que los dos únicos parciales existen **antes** de que caiga la constraint de
  v61, porque el intervalo entre ambas cosas es el único momento en que
  ``pursuits`` podría quedarse sin unicidad;
- que el único parcial del caso «sin lote» reproduce literalmente la garantía
  vieja (``WHERE lote_numero IS NULL``): sin ese predicado, ``NULL <> NULL``
  dejaría abrir el mismo expediente veinte veces.

La comprobación de que una fila preexistente sobrevive intacta necesita
Postgres y vive en ``tests/test_s3_lotes_api.py``.
"""

from __future__ import annotations

import importlib
from contextlib import contextmanager
from typing import Any


class _RecordingOp:
    """``op`` de mentira: anota el SQL en el orden en que se ejecuta."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.autocommit_blocks = 0

    def execute(self, statement: Any) -> None:
        self.statements.append(" ".join(str(statement).split()))

    def get_context(self) -> _RecordingOp:
        return self

    @contextmanager
    def autocommit_block(self) -> Any:
        self.autocommit_blocks += 1
        yield


def _load_migration() -> Any:
    return importlib.import_module("db.alembic.versions.v110_pursuits_lote_id")


def _run(monkeypatch: Any, sentido: str) -> _RecordingOp:
    migration = _load_migration()
    monkeypatch.setattr(migration, "_is_postgres", lambda: True)
    fake_op = _RecordingOp()
    monkeypatch.setattr(migration, "op", fake_op)
    getattr(migration, sentido)()
    return fake_op


def _indice(statements: list[str], nombre: str) -> int:
    for posicion, statement in enumerate(statements):
        if nombre in statement:
            return posicion
    raise AssertionError(f"No se ejecutó ninguna sentencia con {nombre!r}: {statements}")


def test_v110_encadena_con_v109() -> None:
    """Una migración fuera de la cadena no se aplica nunca."""
    migration = _load_migration()

    assert migration.revision == "v110_pursuits_lote_id"
    assert migration.down_revision == "v109_watchlist_rules_campos"


def test_v110_es_noop_fuera_de_postgres(monkeypatch: Any) -> None:
    """El guard de dialecto: v48 hacía ``return`` en Postgres, el error inverso."""
    migration = _load_migration()
    monkeypatch.setattr(migration, "_is_postgres", lambda: False)

    class _FailingOp:
        def __getattr__(self, name: str) -> Any:
            def _boom(*args: Any, **kwargs: Any) -> None:
                raise AssertionError(f"no debería llamarse: op.{name}")

            return _boom

    monkeypatch.setattr(migration, "op", _FailingOp())

    migration.upgrade()
    migration.downgrade()


def test_v110_anade_columnas_nullables_sin_default(monkeypatch: Any) -> None:
    """Metadata-only: sin reescritura de tabla y sin tocar las filas de hoy.

    Un ``DEFAULT`` o un ``NOT NULL`` convertirían esto en la v68 —1,6 M filas
    reescritas con lock exclusivo— y además cambiarían el valor de las filas
    existentes, que tienen que quedarse en ``NULL`` porque ``NULL`` es su
    verdad: se abrieron para el expediente completo y sin desglose sellado.
    """
    fake_op = _run(monkeypatch, "upgrade")

    columnas = [s for s in fake_op.statements if "ADD COLUMN" in s]
    assert any("lote_numero TEXT" in s for s in columnas)
    assert any("desglose_al_abrir TEXT" in s for s in columnas)
    for statement in columnas:
        assert "DEFAULT" not in statement.upper()
        assert "NOT NULL" not in statement.upper()


def test_v110_construye_los_dos_unicos_antes_de_borrar_el_viejo(monkeypatch: Any) -> None:
    """El orden es la garantía: nunca un instante sin unicidad (lección de v86)."""
    fake_op = _run(monkeypatch, "upgrade")

    sin_lote = _indice(fake_op.statements, "uq_pursuits_org_lic_sin_lote")
    con_lote = _indice(fake_op.statements, "uq_pursuits_org_lic_lote")
    drop = _indice(fake_op.statements, "DROP CONSTRAINT")

    assert sin_lote < drop
    assert con_lote < drop
    # Los dos se construyen sin bloquear escrituras sobre una tabla viva.
    assert "CREATE UNIQUE INDEX CONCURRENTLY" in fake_op.statements[sin_lote]
    assert "CREATE UNIQUE INDEX CONCURRENTLY" in fake_op.statements[con_lote]
    assert fake_op.autocommit_blocks == 1


def test_v110_los_unicos_son_parciales_y_complementarios(monkeypatch: Any) -> None:
    """Sin los dos predicados no hay protección: ``NULL <> NULL`` en SQL.

    Una ``UNIQUE (organization_id, licitacion_id, lote_numero)`` a secas dejaría
    a las filas sin lote —hoy el 100 %— sin ninguna unicidad, que es el mismo
    agujero que v65 tapó en ``adjudicaciones``.
    """
    fake_op = _run(monkeypatch, "upgrade")

    sin_lote = fake_op.statements[_indice(fake_op.statements, "uq_pursuits_org_lic_sin_lote")]
    con_lote = fake_op.statements[_indice(fake_op.statements, "uq_pursuits_org_lic_lote")]

    assert "(organization_id, licitacion_id) WHERE lote_numero IS NULL" in sin_lote
    assert "(organization_id, licitacion_id, lote_numero) WHERE lote_numero IS NOT NULL" in con_lote


def test_v110_no_crea_ninguna_fk_contra_lotes(monkeypatch: Any) -> None:
    """La FK contra ``lotes.id`` es justo lo que no se puede escribir.

    ``db/upsert.py::replace_lotes`` borra y reinserta los lotes del expediente
    en cada re-ingesta. Con una FK, esa pasada nocturna borraría el pursuit
    (CASCADE), lo convertiría en uno del expediente entero (SET NULL) o
    reventaría la ingesta (RESTRICT). Por eso se persiste el número, que es la
    parte estable de la identidad del lote.
    """
    fake_op = _run(monkeypatch, "upgrade")

    for statement in fake_op.statements:
        assert "REFERENCES lotes" not in statement
        assert "FOREIGN KEY" not in statement.upper()


def test_v110_downgrade_restaura_la_unique_antes_de_soltar_los_indices(
    monkeypatch: Any,
) -> None:
    """Bajar tampoco puede dejar la tabla sin unicidad ni un instante.

    Y si alguna organización ya abrió dos lotes del mismo expediente, este
    ``ADD CONSTRAINT`` falla y el downgrade se detiene: bajar borraría trabajo
    del equipo, así que es correcto que no pueda completarse en silencio.
    """
    fake_op = _run(monkeypatch, "downgrade")

    restaura = _indice(fake_op.statements, "ADD CONSTRAINT uq_pursuits_org_licitacion")
    suelta = _indice(fake_op.statements, "DROP INDEX CONCURRENTLY")
    borra_columna = _indice(fake_op.statements, "DROP COLUMN IF EXISTS lote_numero")

    assert restaura < suelta < borra_columna
