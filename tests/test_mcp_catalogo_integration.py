"""Ratchet del catálogo del MCP interno contra el esquema real migrado.

Cada tabla nueva de una migración obliga a clasificarla en
``mcp_server/catalogo.py``; cada columna con nombre de secreto obliga a
excluirla o a dejar escrito por qué no lo es (``COLUMNAS_REVISADAS``).
"""

from __future__ import annotations

import os
import re
import secrets
from collections.abc import Iterator
from typing import Any

import pytest

from mcp_server.catalogo import (
    CATALOGO,
    COLUMNAS_REVISADAS,
    Visibilidad,
    sentencias_grants,
    sentencias_rol,
)

_PARECE_SECRETO = re.compile(r"(hash|secret|token|password|passwd|clave|key|totp|salt)", re.I)


def _columnas_por_tabla(db_mod: Any) -> dict[str, list[str]]:
    """Columnas de las BASE TABLE del schema del test, sin ``alembic_version``."""
    with db_mod.connect() as c:
        filas = c.execute(
            """
            SELECT t.table_name, c.column_name
            FROM information_schema.tables t
            JOIN information_schema.columns c
              ON c.table_schema = t.table_schema AND c.table_name = t.table_name
            WHERE t.table_schema = current_schema()
              AND t.table_type = 'BASE TABLE'
              AND t.table_name <> 'alembic_version'
            ORDER BY t.table_name, c.ordinal_position
            """
        ).fetchall()
    out: dict[str, list[str]] = {}
    for tabla, columna in filas:
        out.setdefault(str(tabla), []).append(str(columna))
    return out


def test_toda_tabla_clasificada(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    reales = set(_columnas_por_tabla(db_mod))
    sin_clasificar = reales - set(CATALOGO)
    assert sin_clasificar == set(), f"Clasifica en mcp_server/catalogo.py: {sorted(sin_clasificar)}"
    # Una entrada que apunta a una tabla inexistente es un renombrado olvidado.
    huerfanas = set(CATALOGO) - reales
    assert huerfanas == set(), f"Entradas sin tabla real: {sorted(huerfanas)}"


def test_columnas_de_tablas_con_exclusiones_cubiertas(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    reales = _columnas_por_tabla(db_mod)
    for entrada in CATALOGO.values():
        if entrada.visibilidad is not Visibilidad.COLUMNAS_EXCLUIDAS:
            continue
        declaradas = set(entrada.columnas_permitidas) | set(entrada.columnas_excluidas)
        assert set(reales[entrada.tabla]) == declaradas, (
            f"{entrada.tabla}: columnas sin clasificar "
            f"{sorted(set(reales[entrada.tabla]) - declaradas)}, "
            f"columnas inexistentes {sorted(declaradas - set(reales[entrada.tabla]))}"
        )


def test_ninguna_columna_visible_parece_secreta_sin_revisar(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    reales = _columnas_por_tabla(db_mod)
    sospechosas: set[tuple[str, str]] = set()
    for entrada in CATALOGO.values():
        if entrada.visibilidad is Visibilidad.OCULTA:
            continue
        if entrada.visibilidad is Visibilidad.VISIBLE:
            visibles = reales[entrada.tabla]
        else:
            visibles = list(entrada.columnas_permitidas)
        for col in visibles:
            if _PARECE_SECRETO.search(col) and (entrada.tabla, col) not in COLUMNAS_REVISADAS:
                sospechosas.add((entrada.tabla, col))
    assert sospechosas == set(), (
        "Columnas con nombre de secreto: exclúyelas en mcp_server/catalogo.py o "
        f"añádelas a COLUMNAS_REVISADAS con el motivo: {sorted(sospechosas)}"
    )


def test_columnas_revisadas_existen(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    reales = _columnas_por_tabla(db_mod)
    for tabla, col in COLUMNAS_REVISADAS:
        assert col in reales.get(tabla, []), f"COLUMNAS_REVISADAS obsoleta: {tabla}.{col}"


@pytest.fixture()
def rol_mcp_efimero(tmp_db: Any) -> Iterator[str]:
    """Rol con nombre único (los roles son globales al clúster y hay paralelismo)."""
    db_mod, _ = tmp_db
    rol = f"tf_mcp_probe_{os.getpid()}_{secrets.token_hex(4)}"
    with db_mod.connect() as c:
        c.execute(f'CREATE ROLE "{rol}" NOLOGIN NOBYPASSRLS')
    try:
        yield rol
    finally:
        with db_mod.connect() as c:
            c.execute(f'DROP OWNED BY "{rol}"')
            c.execute(f'DROP ROLE IF EXISTS "{rol}"')


def test_grants_aplican_en_postgres(tmp_db: Any, rol_mcp_efimero: str) -> None:
    db_mod, _ = tmp_db
    rol = rol_mcp_efimero
    with db_mod.connect() as c:
        schema = str(c.execute("SELECT current_schema()").fetchone()[0])
        for sentencia in sentencias_rol(rol):
            c.execute(sentencia)
        # Todas las tablas visibles existen; las OCULTAS futuras no se mencionan.
        for sentencia in sentencias_grants(rol, schema):
            c.execute(sentencia)
        # Re-ejecutar es idempotente.
        for sentencia in sentencias_grants(rol, schema):
            c.execute(sentencia)
        limites = c.execute(
            "SELECT rolconfig, rolconnlimit, rolinherit, rolbypassrls FROM pg_roles "
            "WHERE rolname = %s",
            (rol,),
        ).fetchone()
        assert limites is not None
        config = set(limites[0])
        assert "default_transaction_read_only=on" in config
        assert "statement_timeout=15s" in config
        assert limites[1] == 5
        assert limites[2] is False
        assert limites[3] is False
        # Sin INSERT/UPDATE/DELETE/TRUNCATE sobre ninguna tabla.
        escritura = c.execute(
            "SELECT count(*) FROM information_schema.role_table_grants "
            "WHERE grantee = %s AND privilege_type <> 'SELECT'",
            (rol,),
        ).fetchone()
        assert escritura is not None and escritura[0] == 0
        # La política existe en cada tabla visible y no en las ocultas.
        con_politica = {
            str(r[0])
            for r in c.execute(
                "SELECT tablename FROM pg_policies WHERE schemaname = %s "
                "AND policyname = 'tenderflow_mcp_read'",
                (schema,),
            ).fetchall()
        }
        visibles = {e.tabla for e in CATALOGO.values() if e.visibilidad is not Visibilidad.OCULTA}
        assert con_politica == visibles
        # password_hash no es legible, el resto de users sí.
        puede = c.execute(
            "SELECT has_column_privilege(%s, %s, 'password_hash', 'SELECT'), "
            "has_column_privilege(%s, %s, 'email', 'SELECT'), "
            "has_table_privilege(%s, %s, 'SELECT')",
            (rol, f"{schema}.users", rol, f"{schema}.users", rol, f"{schema}.api_keys"),
        ).fetchone()
        assert puede is not None
        assert puede[0] is False
        assert puede[1] is True
        assert puede[2] is False


def test_grants_abortan_sin_revocar_si_falta_una_tabla_visible(
    tmp_db: Any, rol_mcp_efimero: str
) -> None:
    """Ejecutar antes de las migraciones no puede dejar el rol a medias."""
    db_mod, _ = tmp_db
    rol = rol_mcp_efimero
    with db_mod.connect() as c:
        schema = str(c.execute("SELECT current_schema()").fetchone()[0])
        sentencias = sentencias_grants(rol, schema)
        # Estado previo: un permiso que un REVOKE a medias se llevaría por delante.
        c.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO "{rol}"')
        c.execute(f'GRANT SELECT ON "{schema}"."lotes" TO "{rol}"')
        c.execute(f'DROP TABLE "{schema}"."ute_miembros" CASCADE')

    with db_mod.connect() as c:
        with pytest.raises(Exception, match="ute_miembros") as exc:
            for sentencia in sentencias:
                c.execute(sentencia)
        assert "faltan tablas visibles" in str(exc.value)

    with db_mod.connect() as c:
        conserva = c.execute(
            "SELECT has_table_privilege(%s, %s, 'SELECT')", (rol, f"{schema}.lotes")
        ).fetchone()
        assert conserva is not None and conserva[0] is True
        politicas = c.execute(
            "SELECT count(*) FROM pg_policies WHERE policyname = 'tenderflow_mcp_read' "
            "AND schemaname = %s",
            (schema,),
        ).fetchone()
        assert politicas is not None and politicas[0] == 0
