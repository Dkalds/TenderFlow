"""Catálogo de visibilidad del MCP interno: reglas y SQL generado (unitarios)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_server.catalogo import (
    CATALOGO,
    DOMINIOS,
    Visibilidad,
    entrada_visible,
    sentencias_grants,
    sentencias_rol,
    tablas_visibles,
)

_RAIZ = Path(__file__).resolve().parent.parent


def test_rol_lleva_los_limites_del_spec() -> None:
    sql = "\n".join(sentencias_rol("tenderflow_mcp"))
    for fragmento in (
        "default_transaction_read_only = on",
        "statement_timeout = '15s'",
        "idle_in_transaction_session_timeout = '30s'",
        "work_mem = '32MB'",
        "search_path = pg_catalog, public",
        "NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS",
        "CONNECTION LIMIT 5",
        "no puede ser superusuario",
    ):
        assert fragmento in sql


def test_rol_no_toca_el_atributo_superuser() -> None:
    # Postgres 16+ exige ser superusuario para tocar SUPERUSER, aunque sea para
    # quitarlo, y el `postgres` de Supabase no lo es: el script abortaba con 42501.
    sql = "\n".join(sentencias_rol("tenderflow_mcp"))
    assert re.search(r"\b(NO)?SUPERUSER\b", sql) is None


def test_tablas_de_credenciales_ocultas() -> None:
    for t in (
        "api_keys",
        "sessions",
        "totp_secrets",
        "totp_recovery_codes",
        "password_reset_tokens",
        "idempotency_keys",
        "rate_limits",
        "audit_chain_state",
        "mcp_oauth_clients",
        "mcp_oauth_tokens",
    ):
        assert CATALOGO[t].visibilidad is Visibilidad.OCULTA


def test_users_sin_password_hash() -> None:
    e = CATALOGO["users"]
    assert e.visibilidad is Visibilidad.COLUMNAS_EXCLUIDAS
    assert "password_hash" in e.columnas_excluidas
    assert "password_hash" not in e.columnas_permitidas


def test_grants_no_mencionan_tablas_ocultas() -> None:
    sql = "\n".join(sentencias_grants())
    assert "api_keys" not in sql
    assert "GRANT SELECT ON public.licitaciones" in sql.replace('"', "")
    assert "INSERT" not in sql
    assert "UPDATE" not in sql
    assert "DELETE" not in sql


def test_grants_por_columna_omiten_las_excluidas() -> None:
    sql = "\n".join(sentencias_grants()).replace('"', "")
    assert "password_hash" not in sql
    assert "GRANT SELECT (" in sql


def test_grants_incluyen_politica_idempotente() -> None:
    sql = "\n".join(sentencias_grants())
    assert "CREATE POLICY tenderflow_mcp_read" in sql
    assert "FOR SELECT" in sql
    assert "USING (true)" in sql
    assert "IF NOT EXISTS" in sql


def test_grants_empiezan_comprobando_que_existen_las_tablas_visibles() -> None:
    sentencias = sentencias_grants()
    assert "faltan tablas visibles" in sentencias[0]
    assert "to_regclass" in sentencias[0]
    assert sentencias[1].startswith("REVOKE")
    assert not any("REVOKE" in x for x in sentencias[:1])


def test_entrada_visible_es_exacta() -> None:
    assert entrada_visible("licitaciones") is not None
    assert entrada_visible("api_keys") is None
    assert entrada_visible("Licitaciones") is None
    assert entrada_visible('users"; --') is None
    assert entrada_visible("pg_shadow") is None


def test_tablas_visibles_ordenadas_y_sin_ocultas() -> None:
    visibles = tablas_visibles()
    assert visibles
    assert all(e.visibilidad is not Visibilidad.OCULTA for e in visibles)
    clave = [(DOMINIOS.index(e.dominio), e.tabla) for e in visibles]
    assert clave == sorted(clave)


def test_dominios_y_descripciones_completos() -> None:
    for e in CATALOGO.values():
        assert e.dominio in DOMINIOS, e.tabla
        assert e.descripcion.strip(), e.tabla
        assert CATALOGO[e.tabla] is e


def test_columnas_solo_en_tablas_con_exclusiones() -> None:
    for e in CATALOGO.values():
        if e.visibilidad is Visibilidad.COLUMNAS_EXCLUIDAS:
            assert e.columnas_permitidas and e.columnas_excluidas, e.tabla
            assert not set(e.columnas_permitidas) & set(e.columnas_excluidas), e.tabla
        else:
            assert not e.columnas_permitidas and not e.columnas_excluidas, e.tabla


def test_identificadores_peligrosos_se_rechazan() -> None:
    with pytest.raises(ValueError):
        sentencias_rol('x"; DROP ROLE y; --')
    with pytest.raises(ValueError):
        sentencias_grants("tenderflow_mcp", 'public"; --')


def test_sql_generado_al_dia() -> None:
    res = subprocess.run(
        [sys.executable, "scripts/gen_mcp_grants.py", "--check"],
        cwd=_RAIZ,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stdout + res.stderr
