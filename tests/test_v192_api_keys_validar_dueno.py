"""v192: ``VALIDATE CONSTRAINT`` de la restricción de ``v183`` sobre ``api_keys``.

* **Unit** (sin BD): cadena, y que valida después de comprobar.
* **Postgres** (``tmp_db``): con la restricción ``NOT VALID`` y una heredada
  activa sin dueño, para con el recuento y no valida; revocada, valida, y
  reaplicar no falla.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import pytest

_MIGRACION = "db.alembic.versions.v192_api_keys_validar_dueno"


def _load() -> Any:
    return importlib.import_module(_MIGRACION)


def test_cadena() -> None:
    migracion = _load()
    assert migracion.revision == "v192_api_keys_validar_dueno"
    assert migracion.down_revision == "v191_adj_identidad_normalizada"


def test_comprueba_antes_de_validar(monkeypatch: pytest.MonkeyPatch) -> None:
    migracion = _load()
    sentencias: list[str] = []
    fake_op = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
        execute=lambda s: sentencias.append(str(s)),
    )
    monkeypatch.setattr(migracion, "op", fake_op)
    migracion.upgrade()
    assert "RAISE EXCEPTION" in sentencias[0]
    assert sentencias[-1] == "ALTER TABLE api_keys VALIDATE CONSTRAINT ck_api_keys_activa_con_dueno"


# ── Postgres ───────────────────────────────────────────────────────────────


def _validada(c: Any) -> bool:
    fila = c.execute(
        "SELECT convalidated FROM pg_constraint "
        "WHERE conname = 'ck_api_keys_activa_con_dueno' AND conrelid = 'api_keys'::regclass"
    ).fetchone()
    return bool(fila[0])


def _aplicar(c: Any) -> None:
    migracion = _load()
    fake_op = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
        execute=lambda s: c.execute(str(s)),
    )
    original = migracion.op
    migracion.op = fake_op
    try:
        migracion.upgrade()
    finally:
        migracion.op = original


def test_para_con_una_heredada_activa_y_valida_tras_revocarla(tmp_db) -> None:
    import psycopg

    from db.database import now_utc_iso

    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        # Como en producción antes de v192: la restricción sin validar y una
        # clave heredada activa, sin dueño ni caducidad.
        c.execute("ALTER TABLE api_keys DROP CONSTRAINT ck_api_keys_activa_con_dueno")
        c.execute(
            "INSERT INTO api_keys (key_hash, name, created_at, is_active) "
            "VALUES (%s, 'heredada', %s, 1)",
            ("h" * 64, now_utc_iso()),
        )
        c.execute(
            "ALTER TABLE api_keys ADD CONSTRAINT ck_api_keys_activa_con_dueno CHECK "
            "(is_active = 0 OR (user_id IS NOT NULL AND expires_at IS NOT NULL)) NOT VALID"
        )

    with pytest.raises(psycopg.errors.RaiseException, match="1 claves"), db_mod.connect() as c:
        _aplicar(c)
    with db_mod.connect() as c:
        assert not _validada(c)

    with db_mod.connect() as c:
        c.execute("UPDATE api_keys SET is_active = 0")
        _aplicar(c)
        _aplicar(c)  # reaplicar no falla
        assert _validada(c)
