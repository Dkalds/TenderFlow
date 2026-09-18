"""v135 (ADR-030 fase 3): la PK de ``user_profiles`` y ``radar_dismissals`` es ``user_id``.

Dos bloques:

* **Unit** (sin BD): cadena de revisiones y forma del DDL —que las
  comprobaciones que abortan van antes del primer ``ALTER``, que la PK vieja
  queda como índice único de transición y que el downgrade deshace lo mismo—.
* **Postgres** (``tmp_db``): lo que la migración promete sobre datos reales.
  La fixture aplica ``alembic upgrade head`` sobre una base vacía, así que el
  backfill y el ``RAISE`` se ejercitan ejecutando el SQL público de la
  revisión sobre filas sembradas, igual que hace
  ``tests/test_user_id_cambio_email_integration.py`` con v129.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import pytest

_MIGRACION = "db.alembic.versions.v135_user_id_pk_fase3"


def _load() -> Any:
    return importlib.import_module(_MIGRACION)


class _Inspector:
    def __init__(self, tablas: list[str]) -> None:
        self._tablas = tablas

    def get_table_names(self) -> list[str]:
        return self._tablas


class _PostgresOp:
    def __init__(self) -> None:
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        self.statements: list[str] = []

    def get_bind(self) -> Any:
        return self.bind

    def execute(self, statement: Any) -> None:
        self.statements.append(str(statement))


def _ejecutar(monkeypatch: pytest.MonkeyPatch, paso: str) -> str:
    migracion = _load()
    fake_op = _PostgresOp()
    monkeypatch.setattr(migracion, "op", fake_op)
    monkeypatch.setattr(
        migracion.sa, "inspect", lambda _bind: _Inspector([*migracion.TABLAS, "users"])
    )
    getattr(migracion, paso)()
    return "\n".join(fake_op.statements)


# ── Unit ────────────────────────────────────────────────────────────────────


def test_cadena_e_inventario() -> None:
    migracion = _load()
    assert migracion.revision == "v135_user_id_pk_fase3"
    assert migracion.down_revision == "v136_tecnologia_verdad_unica"
    assert migracion.PK_NUEVA == {
        "user_profiles": ("user_id",),
        "radar_dismissals": ("user_id", "id_externo"),
    }
    assert migracion.PK_VIEJA == {
        "user_profiles": ("user_key",),
        "radar_dismissals": ("user_key", "id_externo"),
    }


def test_clave_sql_es_la_de_v129() -> None:
    """La derivación no puede divergir entre las dos fases: v129 ya probó la
    suya contra ``user_key_from_email`` clave a clave."""
    v129 = importlib.import_module("db.alembic.versions.v129_user_id_fase2")
    assert _load().CLAVE_SQL == v129.CLAVE_SQL


def test_no_hace_nada_fuera_de_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    migracion = _load()
    monkeypatch.setattr(migracion, "_is_postgres", lambda: False)

    class _FailingOp:
        def execute(self, statement: Any) -> None:
            raise AssertionError(f"SQL inesperado: {statement}")

    monkeypatch.setattr(migracion, "op", _FailingOp())
    migracion.upgrade()
    migracion.downgrade()


def test_upgrade_comprueba_antes_de_tocar_nada(monkeypatch: pytest.MonkeyPatch) -> None:
    migracion = _load()
    sql = _ejecutar(monkeypatch, "upgrade")

    for tabla in migracion.TABLAS:
        assert migracion.sql_backfill(tabla) in sql
        assert f"fila(s) de {tabla} sin user_id" in sql
        assert f"identidad(es) duplicada(s) en {tabla}" in sql
    # Backfill → comprobaciones → primer DDL, en ese orden.
    primer_ddl = sql.index("DROP CONSTRAINT %I")
    assert sql.index("UPDATE user_profiles AS x SET user_id") < sql.index("RAISE EXCEPTION")
    assert sql.rindex("RAISE EXCEPTION") < primer_ddl


def test_upgrade_mueve_la_pk_y_deja_la_vieja_como_unica(monkeypatch: pytest.MonkeyPatch) -> None:
    sql = _ejecutar(monkeypatch, "upgrade")

    assert "ADD CONSTRAINT pk_user_profiles PRIMARY KEY (user_id)" in sql
    assert "ADD CONSTRAINT pk_radar_dismissals PRIMARY KEY (user_id, id_externo)" in sql
    for tabla in ("user_profiles", "radar_dismissals"):
        assert f"ALTER TABLE {tabla} ALTER COLUMN user_id SET NOT NULL" in sql
        assert f"ALTER TABLE {tabla} ALTER COLUMN user_key DROP NOT NULL" in sql
        assert "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE" in sql
    # Transición: el ``ON CONFLICT`` del código de la fase 2 necesita casar.
    assert (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_profiles_user_key ON user_profiles (user_key)"
        in sql
    )
    assert (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_radar_dismissals_user_key "
        "ON radar_dismissals (user_key, id_externo)"
    ) in sql


def test_downgrade_recupera_la_clave_y_vuelve_a_la_pk_vieja(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sql = _ejecutar(monkeypatch, "downgrade")

    assert "SET user_key = substr(encode(sha256(" in sql
    assert "fila(s) de user_profiles sin user_key" in sql
    assert sql.rindex("RAISE EXCEPTION") < sql.index(
        "DROP INDEX IF EXISTS uq_user_profiles_user_key"
    )
    assert "ADD CONSTRAINT pk_user_profiles PRIMARY KEY (user_key)" in sql
    assert "ADD CONSTRAINT pk_radar_dismissals PRIMARY KEY (user_key, id_externo)" in sql
    assert "ON DELETE SET NULL" in sql


def test_el_mensaje_del_raise_escapa_las_comillas() -> None:
    """La consulta viaja dentro de un literal SQL: una comilla sin doblar
    rompería el ``DO`` entero en vez de dar el mensaje."""
    bloque = _load()._exigir_vacio("SELECT 1 WHERE 'a' = 'a'", "prueba")
    assert "''a'' = ''a''" in bloque


# ── Postgres ────────────────────────────────────────────────────────────────


def _crear_usuario(email: str) -> int:
    from db.database import connect, now_utc_iso

    with connect() as c:
        fila = c.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (%s, 'h', %s) "
            "RETURNING id",
            (email, now_utc_iso()),
        ).fetchone()
    return int(fila[0])


def _organizacion_personal(user_id: int) -> int:
    from db.repositories.organizations import OrganizationRepository

    return int(OrganizationRepository().ensure_personal_organization(user_id)["id"])


def test_el_upsert_del_perfil_es_uno_por_usuario_y_no_escribe_clave(tmp_db: Any) -> None:
    from db.database import connect
    from db.repositories.user_profiles import get_own_user_profile, upsert_user_profile

    user_id = _crear_usuario("perfil@v135.test")
    organizacion = _organizacion_personal(user_id)

    upsert_user_profile({"importe_min": 1}, organizacion, user_id=user_id)
    upsert_user_profile({"importe_min": 2}, organizacion, user_id=user_id)

    with connect() as c:
        filas = c.execute(
            "SELECT user_key, importe_min FROM user_profiles WHERE user_id = %s", (user_id,)
        ).fetchall()
    assert [(f[0], f[1]) for f in filas] == [(None, 2)]
    # Se sigue leyendo por la API de siempre, que ya pasa el id.
    perfil = get_own_user_profile("clave-cualquiera", user_id=user_id)
    assert perfil is not None and perfil["importe_min"] == 2


def test_el_descarte_es_uno_por_usuario_y_expediente(tmp_db: Any) -> None:
    """Dos claves distintas del mismo usuario —un cambio de correo— caen en la
    misma fila: lo impide la PK, no el repositorio."""
    from db import radar_dismissals
    from db.database import connect

    user_id = _crear_usuario("descarte@v135.test")
    radar_dismissals.add("clave-vieja", "EXP-1", score=80, user_id=user_id)
    radar_dismissals.add("clave-nueva", "EXP-1", score=10, accion="silenciar", user_id=user_id)

    with connect() as c:
        filas = c.execute(
            "SELECT user_key, score, accion FROM radar_dismissals WHERE user_id = %s",
            (user_id,),
        ).fetchall()
    # La clave de la fila no se reescribe y el score es el de la primera vez (v93).
    assert [(f[0], f[1], f[2]) for f in filas] == [("clave-vieja", 80, "silenciar")]


def test_la_pk_vieja_sigue_casando_para_el_codigo_de_la_fase_2(tmp_db: Any) -> None:
    """El índice de transición: un ``ON CONFLICT (user_key)`` como el que hace
    el código anterior sigue siendo SQL válido sobre el schema nuevo."""
    from db.database import connect, now_utc_iso

    user_id = _crear_usuario("transicion@v135.test")
    organizacion = _organizacion_personal(user_id)
    sql = (
        "INSERT INTO user_profiles (user_key, user_id, updated_at, organization_id, visibility) "
        "VALUES (%s, %s, %s, %s, 'private') "
        "ON CONFLICT (user_key) DO UPDATE SET updated_at = excluded.updated_at"
    )
    with connect() as c:
        c.execute(sql, ("k-fase2", user_id, now_utc_iso(), organizacion))
        c.execute(sql, ("k-fase2", user_id, now_utc_iso(), organizacion))
        n = c.execute(
            "SELECT count(*) FROM user_profiles WHERE user_id = %s", (user_id,)
        ).fetchone()[0]
    assert n == 1


def test_una_fila_sin_user_id_ya_no_se_puede_escribir(tmp_db: Any) -> None:
    import psycopg

    from db.database import connect, now_utc_iso

    with pytest.raises(psycopg.errors.NotNullViolation), connect() as c:
        c.execute(
            "INSERT INTO user_profiles (user_key, updated_at, visibility) "
            "VALUES ('huerfana', %s, 'private')",
            (now_utc_iso(),),
        )


def test_la_comprobacion_aborta_con_huerfanas(tmp_db: Any) -> None:
    """El ``RAISE`` de la migración salta con una fila sin dueño resoluble.

    Sobre el schema ya migrado la columna es ``NOT NULL``, así que se prueba
    el bloque contra una tabla temporal con la misma forma: lo que importa es
    que el ``DO`` aborta, y que su mensaje lleva la consulta para revisarlas.
    """
    import psycopg

    from db.database import connect

    migracion = _load()
    with pytest.raises(psycopg.errors.RaiseException, match="sin user_id"), connect() as c:
        c.execute(
            "CREATE TEMPORARY TABLE v135_prueba (user_key TEXT, user_id INTEGER) ON COMMIT DROP"
        )
        c.execute("INSERT INTO v135_prueba VALUES ('sin-dueno', NULL)")
        c.execute(
            migracion._exigir_vacio(migracion.sql_huerfanas("v135_prueba"), "fila(s) sin user_id")
        )


def test_el_backfill_resuelve_por_la_clave_del_correo(tmp_db: Any) -> None:
    """El paso 1 de la migración, sobre una tabla con la forma de la vieja."""
    from db.database import connect
    from shared.identity import user_key_from_email

    migracion = _load()
    user_id = _crear_usuario("Backfill@V135.test")
    clave = user_key_from_email("Backfill@V135.test", user_id)

    with connect() as c:
        c.execute(
            "CREATE TEMPORARY TABLE v135_prueba (user_key TEXT, user_id INTEGER) ON COMMIT DROP"
        )
        c.execute("INSERT INTO v135_prueba VALUES (%s, NULL)", (clave,))
        c.execute(migracion._CREAR_CLAVES)
        c.execute(migracion._SEMBRAR_CLAVES)
        c.execute(migracion.sql_backfill("v135_prueba"))
        fila = c.execute("SELECT user_id FROM v135_prueba").fetchone()
    assert int(fila[0]) == user_id
