"""v183: ``CHECK … NOT VALID`` — una clave de API activa necesita dueño y caducidad.

* **Unit** (sin BD): cadena y que la restricción va ``NOT VALID`` (las 89
  heredadas siguen hasta que el propietario las revoque).
* **Postgres** (``tmp_db``): una activa sin dueño o sin caducidad no entra; una
  revocada sí. Revocar una heredada lo cubre ``tests/test_admin_api_keys_route.py``.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import pytest

_MIGRACION = "db.alembic.versions.v183_api_keys_activa_con_dueno"


def _load() -> Any:
    return importlib.import_module(_MIGRACION)


def test_cadena() -> None:
    migracion = _load()
    assert migracion.revision == "v183_api_keys_activa_con_dueno"
    assert migracion.down_revision == "v182_unique_user_key_parciales"


def test_la_restriccion_va_sin_validar(monkeypatch: pytest.MonkeyPatch) -> None:
    migracion = _load()
    sentencias: list[str] = []
    fake_op = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
        execute=lambda s: sentencias.append(str(s)),
    )
    monkeypatch.setattr(migracion, "op", fake_op)
    migracion.upgrade()
    (sql,) = sentencias
    assert "NOT VALID" in sql
    assert "VALIDATE" not in sql


# ── Postgres ───────────────────────────────────────────────────────────────

_INSERT = (
    "INSERT INTO api_keys (key_hash, name, created_at, is_active, user_id, expires_at) "
    "VALUES (%s, %s, %s, %s, %s, %s)"
)
_CADUCA = "2099-01-01T00:00:00+00:00"


def _dueno() -> int:
    from tests.claves import dueno_de_prueba

    return dueno_de_prueba("v183")


@pytest.mark.parametrize(
    ("con_dueno", "caduca"),
    [(False, _CADUCA), (True, None), (False, None)],
    ids=["sin-dueno", "sin-caducidad", "sin-nada"],
)
def test_una_activa_sin_dueno_o_sin_caducidad_no_entra(tmp_db, con_dueno, caduca) -> None:
    import psycopg

    from db.database import now_utc_iso

    db_mod, _ = tmp_db
    dueno = _dueno() if con_dueno else None
    with pytest.raises(psycopg.errors.CheckViolation), db_mod.connect() as c:
        c.execute(_INSERT, ("h" * 64, "mala", now_utc_iso(), 1, dueno, caduca))


def test_una_revocada_sin_dueno_si_entra(tmp_db) -> None:
    from db.database import now_utc_iso

    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        c.execute(_INSERT, ("r" * 64, "revocada", now_utc_iso(), 0, None, None))
        c.execute(_INSERT, ("b" * 64, "buena", now_utc_iso(), 1, _dueno(), _CADUCA))
    with db_mod.connect_read() as c:
        assert c.execute("SELECT count(*) FROM api_keys").fetchone()[0] == 2
