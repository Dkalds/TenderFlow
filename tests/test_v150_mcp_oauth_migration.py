"""La forma de v150: lo que la migración emite, sin base.

Lo que el esquema resultante hace con datos lo ejerce
``tests/test_mcp_oauth_integration.py``. Aquí se fija lo que un test contra una
base sin el rol ``tenderflow_app`` no ve: que, si el rol existe, las dos tablas
le dan acceso total tras la migración (``scripts/setup_pg_roles.sql`` §3 solo
cubre las tablas que existían cuando se ejecutó), sin tocar ``FORCE`` ni crear
políticas por tenant (no tienen ``organization_id``).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import patch

_RUTA = Path(__file__).resolve().parents[1] / "db" / "alembic" / "versions" / "v150_mcp_oauth.py"


def _cargar() -> Any:
    spec = importlib.util.spec_from_file_location("v150_mcp_oauth", _RUTA)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _sql_emitido(funcion: str, *, dialecto: str = "postgresql") -> list[str]:
    modulo = _cargar()
    emitido: list[str] = []
    with patch.object(modulo, "op") as op_falso:
        op_falso.get_bind.return_value.dialect.name = dialecto
        op_falso.execute.side_effect = emitido.append
        getattr(modulo, funcion)()
    return emitido


def test_encadena_con_v149() -> None:
    modulo = _cargar()
    assert modulo.revision == "v150_mcp_oauth"
    assert modulo.down_revision == "v149_ledger_borrado_org"


def test_fuera_de_postgres_no_emite_nada() -> None:
    assert _sql_emitido("upgrade", dialecto="sqlite") == []
    assert _sql_emitido("downgrade", dialecto="sqlite") == []


def test_cada_tabla_activa_rls_y_da_acceso_total_a_tenderflow_app() -> None:
    emitido = _sql_emitido("upgrade")
    for tabla in ("mcp_oauth_clients", "mcp_oauth_tokens"):
        assert f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY" in emitido
        bloque = next(
            s
            for s in emitido
            if s.startswith("DO $$") and f"POLICY tenderflow_app_full_access ON {tabla} " in s
        )
        assert "rolname = 'tenderflow_app'" in bloque
        assert f"DROP POLICY IF EXISTS tenderflow_app_full_access ON {tabla};" in bloque
        assert "FOR ALL TO tenderflow_app USING (true) WITH CHECK (true)" in bloque
    todo = "\n".join(emitido)
    assert "FORCE ROW LEVEL SECURITY" not in todo
    assert "tenant_scope" not in todo and "organization_id" not in todo


def test_downgrade_borra_primero_los_tokens() -> None:
    emitido = _sql_emitido("downgrade")
    assert emitido == [
        "DROP TABLE IF EXISTS mcp_oauth_tokens",
        "DROP TABLE IF EXISTS mcp_oauth_clients",
    ]
