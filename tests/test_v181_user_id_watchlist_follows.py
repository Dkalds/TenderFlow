"""v181 (ADR-030 fase 3, cuarta tanda): ``watchlist_*``, ``follows`` y
``pending_digests`` se identifican por ``user_id``.

* **Unit** (sin BD): cadena de revisiones, orden del DDL —función, backfill,
  fusión de ``follows`` y comprobaciones antes del primer índice—, índices
  parciales y ``UNIQUE`` viejos intactos.
* **Postgres** (``tmp_db``): que ``clave_legada_de_usuario`` da exactamente la
  clave de ``shared.identity.user_key_from_email``, que es lo que permite a
  ``db/`` resolver la mitad legacy del predicado sin que nadie le pase la clave.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import pytest

_MIGRACION = "db.alembic.versions.v181_user_id_watchlist_follows"


def _load() -> Any:
    return importlib.import_module(_MIGRACION)


class _Inspector:
    def get_table_names(self) -> list[str]:
        return [*_load().TABLAS_BACKFILL, "users"]


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
    monkeypatch.setattr(migracion.sa, "inspect", lambda _bind: _Inspector())
    getattr(migracion, paso)()
    return "\n".join(fake_op.statements)


def test_cadena_e_identidad() -> None:
    migracion = _load()
    assert migracion.revision == "v181_user_id_watchlist_follows"
    assert migracion.down_revision == "v177_rss_autonomico_sin_tramitacion"
    assert set(migracion.TABLAS_BACKFILL) == {
        "watchlist_cpv",
        "watchlist_items",
        "watchlist_empresas",
        "watchlist_rules",
        "follows",
        "pending_digests",
    }
    assert migracion.TABLAS_UNICAS == {
        "watchlist_items": "id_externo",
        "watchlist_empresas": "empresa_id",
        "follows": "target_type, target_id, kind",
    }


def test_clave_sql_es_la_de_v129() -> None:
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


def test_upgrade_crea_la_funcion_y_comprueba_antes_de_indexar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migracion = _load()
    sql = _ejecutar(monkeypatch, "upgrade")

    assert "CREATE OR REPLACE FUNCTION public.clave_legada_de_usuario(p_user_id integer)" in sql
    assert "LANGUAGE sql STABLE" in sql
    assert "FROM anon" in sql and "FROM authenticated" in sql
    # v59 quitó el EXECUTE por defecto a PUBLIC: el rol de la app lo necesita.
    assert (
        "GRANT EXECUTE ON FUNCTION public.clave_legada_de_usuario(integer) TO tenderflow_app" in sql
    )
    assert sql.index("CREATE OR REPLACE FUNCTION") < sql.index("GRANT EXECUTE")
    for tabla in migracion.TABLAS_BACKFILL:
        assert migracion.sql_backfill(tabla) in sql
    for tabla in ("watchlist_items", "watchlist_empresas"):
        assert f"identidad(es) duplicada(s) en {tabla}" in sql
    assert "identidad(es) duplicada(s) en follows" not in sql
    # Orden: función → backfill → fusión de follows → comprobaciones → índices.
    assert sql.index("CREATE OR REPLACE FUNCTION") < sql.index("SET user_id = k.user_id")
    assert sql.rindex("SET user_id = k.user_id") < sql.index(migracion.sql_deduplicar_follows())
    assert sql.index(migracion.sql_deduplicar_follows()) < sql.index("RAISE EXCEPTION")
    assert sql.rindex("RAISE EXCEPTION") < sql.index("CREATE UNIQUE INDEX")


def test_upgrade_crea_indices_parciales_y_deja_los_unique_viejos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sql = _ejecutar(monkeypatch, "upgrade")

    for tabla, columnas in _load().TABLAS_UNICAS.items():
        assert (
            f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{tabla}_user_id "
            f"ON {tabla} (user_id, {columnas}) WHERE user_id IS NOT NULL"
        ) in sql
    # Ni se retira la clave ni se exige el id: eso es el paso siguiente.
    assert "DROP CONSTRAINT" not in sql
    assert "DROP COLUMN" not in sql
    assert "SET NOT NULL" not in sql


def test_la_fusion_de_follows_conserva_la_ultima_copia() -> None:
    fusion = _load().sql_deduplicar_follows()
    assert fusion.startswith("DELETE FROM follows AS a USING follows AS b")
    assert "a.user_id IS NOT NULL AND a.user_id = b.user_id" in fusion
    assert fusion.endswith("a.id < b.id")


def test_la_comprobacion_ignora_los_null() -> None:
    consulta = _load().sql_duplicados("watchlist_items")
    assert "WHERE user_id IS NOT NULL" in consulta
    assert "GROUP BY user_id, id_externo HAVING count(*) > 1" in consulta


def test_downgrade_quita_indices_y_funcion(monkeypatch: pytest.MonkeyPatch) -> None:
    sql = _ejecutar(monkeypatch, "downgrade")
    for tabla in _load().TABLAS_UNICAS:
        assert f"DROP INDEX IF EXISTS uq_{tabla}_user_id" in sql
    assert "DROP FUNCTION IF EXISTS public.clave_legada_de_usuario(integer)" in sql


# ── Postgres ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "email",
    ["simple@example.com", "MixedCase@Example.COM", "  con.espacios@example.com  ", None],
)
def test_la_funcion_da_la_clave_de_python(tmp_db, email):
    from db.database import connect, now_utc_iso
    from shared.identity import user_key_from_email

    with connect() as c:
        user_id = int(
            c.execute(
                "INSERT INTO users (email, password_hash, created_at) "
                "VALUES (%s, %s, %s) RETURNING id",
                (email, "h", now_utc_iso()),
            ).fetchone()[0]
        )
        clave = c.execute("SELECT clave_legada_de_usuario(%s)", (user_id,)).fetchone()[0]
        sin_usuario = c.execute("SELECT clave_legada_de_usuario(%s)", (user_id + 1000,)).fetchone()
    assert clave == user_key_from_email(email, user_id)
    assert sin_usuario[0] is None
