"""Regresiones unitarias de la migración v76 (``radar_dismissals``).

Las migraciones se aplican por subproceso (``alembic upgrade head`` en
``tests/conftest.py``), así que su código Python no se ejecuta nunca dentro de
la suite: ni se cubre ni se comprueba. Este módulo sigue el patrón de v52/v56/
v58/v59/v64 — cargar el módulo y llamar a ``upgrade()``/``downgrade()`` con un
``op`` de mentira — para fijar lo que la tabla debe ser antes de que exista en
ninguna base real.
"""

from __future__ import annotations

import importlib
from typing import Any

import sqlalchemy as sa


class _RecordingOp:
    """``op`` de mentira: anota qué tablas se crean y qué SQL se ejecuta."""

    def __init__(self) -> None:
        self.created: list[tuple[str, tuple[Any, ...]]] = []
        self.dropped: list[str] = []
        self.statements: list[str] = []

    def create_table(self, name: str, *columns: Any) -> None:
        self.created.append((name, columns))

    def drop_table(self, name: str) -> None:
        self.dropped.append(name)

    def execute(self, statement: Any) -> None:
        self.statements.append(str(statement))


def _load_migration() -> Any:
    return importlib.import_module("db.alembic.versions.v76_radar_dismissals")


def test_v76_encadena_con_v75() -> None:
    """Una migración fuera de la cadena no se aplica nunca."""
    migration = _load_migration()

    assert migration.revision == "v76_radar_dismissals"
    assert migration.down_revision == "v75_users_admin_granted_by"


def test_v76_es_noop_fuera_de_postgres(monkeypatch) -> None:
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


def test_v76_crea_la_tabla_con_pk_compuesta(monkeypatch) -> None:
    """``(user_key, id_externo)`` es lo que hace idempotente al POST.

    Sin esa PK el ``ON CONFLICT DO NOTHING`` del repositorio no tiene sobre qué
    resolver el conflicto y el descarte se duplicaría por cada clic.
    """
    migration = _load_migration()
    monkeypatch.setattr(migration, "_is_postgres", lambda: True)
    fake_op = _RecordingOp()
    monkeypatch.setattr(migration, "op", fake_op)

    migration.upgrade()

    assert [nombre for nombre, _ in fake_op.created] == ["radar_dismissals"]
    nombre, elementos = fake_op.created[0]

    # Los elementos llegan sueltos: una `PrimaryKeyConstraint` sin tabla aún no
    # ha resuelto sus columnas. Montar la `Table` es lo que hace `op` de verdad.
    tabla = sa.Table(nombre, sa.MetaData(), *elementos)

    assert set(tabla.columns.keys()) == {"user_key", "id_externo", "created_at"}
    assert all(not c.nullable for c in tabla.columns)
    assert list(tabla.primary_key.columns.keys()) == ["user_key", "id_externo"]
    assert tabla.primary_key.name == "pk_radar_dismissals"
    assert tabla.c.created_at.server_default is not None


def test_v76_cierra_la_data_api_sobre_la_tabla(monkeypatch) -> None:
    """Tabla per-user: sin esto queda expuesta a ``anon``/``authenticated``."""
    migration = _load_migration()
    monkeypatch.setattr(migration, "_is_postgres", lambda: True)
    fake_op = _RecordingOp()
    monkeypatch.setattr(migration, "op", fake_op)

    migration.upgrade()

    sql = "\n".join(fake_op.statements)
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "REVOKE ALL ON TABLE radar_dismissals FROM anon" in sql
    assert "REVOKE ALL ON TABLE radar_dismissals FROM authenticated" in sql
    assert "TO tenderflow_app" in sql


def test_v76_downgrade_borra_la_tabla(monkeypatch) -> None:
    migration = _load_migration()
    monkeypatch.setattr(migration, "_is_postgres", lambda: True)
    fake_op = _RecordingOp()
    monkeypatch.setattr(migration, "op", fake_op)

    migration.downgrade()

    assert fake_op.dropped == ["radar_dismissals"]
