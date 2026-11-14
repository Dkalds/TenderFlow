"""v182: los ``UNIQUE`` por ``user_key`` pasan a parciales ``WHERE user_id IS NULL``.

* **Unit** (sin BD): cadena de revisiones y orden del DDL —el índice parcial
  antes de quitar el ``UNIQUE`` entero, para no quedar ni un instante sin
  unicidad—.
* **Postgres** (``tmp_db``): quien registra el correo que otra cuenta dejó puede
  seguir lo mismo que ella; antes chocaba con su fila (500/503).
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import pytest

_MIGRACION = "db.alembic.versions.v182_unique_user_key_parciales"


def _load() -> Any:
    return importlib.import_module(_MIGRACION)


class _PostgresOp:
    def __init__(self) -> None:
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        self.statements: list[str] = []

    def get_bind(self) -> Any:
        return self.bind

    def execute(self, statement: Any) -> None:
        self.statements.append(str(statement))


def _ejecutar(monkeypatch: pytest.MonkeyPatch, paso: str) -> list[str]:
    migracion = _load()
    fake_op = _PostgresOp()
    monkeypatch.setattr(migracion, "op", fake_op)
    monkeypatch.setattr(
        migracion.sa,
        "inspect",
        lambda _bind: SimpleNamespace(get_table_names=lambda: [*migracion.TABLAS, "users"]),
    )
    getattr(migracion, paso)()
    return fake_op.statements


def test_cadena() -> None:
    migracion = _load()
    assert migracion.revision == "v182_unique_user_key_parciales"
    assert migracion.down_revision == "v181_user_id_watchlist_follows"


def test_las_tablas_son_las_de_v181() -> None:
    v181 = importlib.import_module("db.alembic.versions.v181_user_id_watchlist_follows")
    assert {t: ", ".join(c) for t, c in _load().TABLAS.items()} == v181.TABLAS_UNICAS


def test_el_indice_parcial_va_antes_de_quitar_el_unique(monkeypatch: pytest.MonkeyPatch) -> None:
    sentencias = _ejecutar(monkeypatch, "upgrade")
    for tabla in _load().TABLAS:
        crea = next(i for i, s in enumerate(sentencias) if f"uq_{tabla}_user_key" in s)
        quita = next(
            i for i, s in enumerate(sentencias) if "DROP CONSTRAINT" in s and f"'{tabla}'" in s
        )
        assert crea < quita
        assert "WHERE user_id IS NULL" in sentencias[crea]


def test_quita_el_unique_por_sus_columnas_no_por_nombre() -> None:
    sql = _load().sql_quitar_unique_entero("watchlist_empresas")
    assert "contype = 'u'" in sql
    assert "ARRAY['user_key', 'empresa_id']" in sql


def test_no_hace_nada_fuera_de_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    migracion = _load()
    monkeypatch.setattr(migracion, "_is_postgres", lambda: False)
    fake_op = _PostgresOp()
    monkeypatch.setattr(migracion, "op", fake_op)
    migracion.upgrade()
    migracion.downgrade()
    assert fake_op.statements == []


def test_downgrade_recupera_los_unique_enteros(monkeypatch: pytest.MonkeyPatch) -> None:
    sentencias = "\n".join(_ejecutar(monkeypatch, "downgrade"))
    assert "uq_follows_user_target UNIQUE (user_key, target_type, target_id, kind)" in sentencias
    assert "DROP INDEX IF EXISTS uq_watchlist_items_user_key" in sentencias


# ── Postgres ───────────────────────────────────────────────────────────────


def test_un_correo_reutilizado_puede_seguir_lo_mismo_que_su_antiguo_dueno(tmp_db) -> None:
    from db import watchlist_empresas as vigilancia
    from db.repositories.organizations import OrganizationRepository
    from db.repositories.watchlist import WatchlistRepository
    from db.users import create_user

    db_mod, _ = tmp_db

    def _usuario(correo: str) -> tuple[int, int]:
        uid = create_user(email=correo, password_hash="x")  # pragma: allowlist secret
        return uid, int(OrganizationRepository().ensure_personal_organization(uid)["id"])

    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) VALUES (%s, %s, %s)",
            ("EXP-REUSO", "Servicio SAP", "2026-11-01T00:00:00+00:00"),
        )
        empresa_id = int(
            c.execute(
                "INSERT INTO empresas (nombre_canonico, created_at, updated_at) "
                "VALUES (%s, %s, %s) RETURNING empresa_id",
                ("ACME SL", "2026-11-01T00:00:00+00:00", "2026-11-01T00:00:00+00:00"),
            ).fetchone()[0]
        )

    antigua, org_antigua = _usuario("reusado@example.test")
    WatchlistRepository().add_item(antigua, "EXP-REUSO", org_antigua)
    vigilancia.add_entry(
        vigilancia.WatchlistEmpresaEntry(
            user_id=antigua, empresa_id=empresa_id, organization_id=org_antigua
        )
    )
    with db_mod.connect() as c:
        c.execute("UPDATE users SET email = %s WHERE id = %s", ("otro@example.test", antigua))

    # La cuenta nueva hereda la clave del correo y sigue lo mismo.
    nueva, org_nueva = _usuario("reusado@example.test")
    favorito = WatchlistRepository().add_item(nueva, "EXP-REUSO", org_nueva)
    assert favorito["user_id"] == nueva
    assert (
        vigilancia.add_entry(
            vigilancia.WatchlistEmpresaEntry(
                user_id=nueva, empresa_id=empresa_id, organization_id=org_nueva
            )
        )
        is not None
    )
    with db_mod.connect_read() as c:
        seguidores = c.execute(
            "SELECT user_id FROM follows WHERE target_type = 'licitacion' "
            "AND target_id = 'EXP-REUSO' ORDER BY user_id"
        ).fetchall()
    assert [int(f[0]) for f in seguidores] == sorted([antigua, nueva])


def test_las_filas_sin_id_siguen_siendo_unicas_por_clave(tmp_db) -> None:
    import psycopg

    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) VALUES (%s, %s, %s)",
            ("EXP-SIN-ID", "Servicio SAP", "2026-11-01T00:00:00+00:00"),
        )
        c.execute(
            "INSERT INTO watchlist_items (user_key, id_externo) VALUES ('clave-vieja', 'EXP-SIN-ID')"
        )
    with pytest.raises(psycopg.errors.UniqueViolation), db_mod.connect() as c:
        c.execute(
            "INSERT INTO watchlist_items (user_key, id_externo) VALUES ('clave-vieja', 'EXP-SIN-ID')"
        )
