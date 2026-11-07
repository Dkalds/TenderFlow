"""SQL del rol de solo lectura del MCP interno (``tenderflow_mcp``).

Solo **genera cadenas**: nada aquí abre una conexión. Las ejecuta un humano con
el rol dueño (``scripts/setup_pg_role_mcp.sql``, generado por
``scripts/gen_mcp_grants.py``) o un test contra un rol efímero.

Qué tablas y columnas se conceden no se decide aquí: lo decide el catálogo de
``mcp_server/catalogo.py``, que llama a estas funciones con su lista de tablas
visibles. Este módulo solo sabe escribir el SQL de esa política.

Todo identificador (rol, schema, política, tabla, columna) pasa por una lista
blanca estricta (``^[a-z_][a-z0-9_]*$``) antes de quedar en el texto, entre
comillas dobles o como literal: la lista blanca no admite ni ``'`` ni ``"``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

__all__ = ["sentencias_grants", "sentencias_rol"]

_IDENTIFICADOR = re.compile(r"[a-z_][a-z0-9_]*")


def _ident(nombre: str) -> str:
    """Identificador SQL entre comillas dobles tras validarlo contra la lista blanca."""
    if not _IDENTIFICADOR.fullmatch(nombre):  # no `match` + `$`: `$` admite un `\n` final
        raise ValueError(f"Identificador SQL no válido: {nombre!r}")
    return f'"{nombre}"'


def sentencias_rol(rol: str) -> list[str]:
    """``ALTER ROLE`` con los límites del rol de solo lectura (sin ``;`` final).

    No lleva ``NOSUPERUSER``: desde Postgres 16 tocar ese atributo, aunque sea
    para quitarlo, exige ser superusuario, y el ``postgres`` de Supabase no lo
    es (el script abortaba con 42501 en producción). Un rol creado por un no
    superusuario nace ``NOSUPERUSER``; la primera sentencia lo comprueba y
    aborta si no fuera así.

    ``extra_float_digits = 3``: Supabase fija ``0`` en su fichero de
    configuración, y con ``0`` Postgres envía los ``real`` con 6 cifras
    significativas (``11782155`` llega como ``1.17822e+07``). El SQL libre
    devolvería importes adjudicados redondeados a la centena de miles.
    """
    r = _ident(rol)
    return [
        "DO $$ BEGIN IF (SELECT rolsuper FROM pg_roles WHERE rolname = "
        f"'{rol}') THEN RAISE EXCEPTION '{rol} no puede ser superusuario'; "
        "END IF; END $$",
        f"ALTER ROLE {r} NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION "
        "NOBYPASSRLS CONNECTION LIMIT 5",
        f"ALTER ROLE {r} SET default_transaction_read_only = on",
        f"ALTER ROLE {r} SET statement_timeout = '15s'",
        f"ALTER ROLE {r} SET idle_in_transaction_session_timeout = '30s'",
        f"ALTER ROLE {r} SET work_mem = '32MB'",
        f"ALTER ROLE {r} SET search_path = pg_catalog, public",
        f"ALTER ROLE {r} SET extra_float_digits = 3",
    ]


def sentencias_grants(
    rol: str,
    schema: str,
    tablas: Sequence[tuple[str, tuple[str, ...] | None]],
    politica: str,
) -> list[str]:
    """``GRANT`` de solo lectura por tabla y la política RLS ``politica``, sin ``;`` final.

    ``tablas`` lleva, en el orden en que se conceden, ``(tabla, columnas)``:
    ``columnas`` es ``None`` para conceder la tabla entera, o la tupla de
    columnas que el rol puede leer.

    Idempotente: parte de un ``REVOKE`` completo, de modo que volver a ejecutarlo
    tras ocultar una tabla o una columna retira lo que ya no corresponde.

    La primera sentencia aborta con un error claro si falta alguna tabla
    (típico: ejecutar el script antes de ``alembic upgrade head``), antes de
    revocar nada: sin ella, un ``GRANT`` fallido deja pasar el resto y el único
    ``DO`` de políticas se desharía entero, dejando al rol sin filas y sin error.
    """
    r = _ident(rol)
    s = _ident(schema)
    _ident(politica)
    for tabla, columnas in tablas:
        _ident(tabla)
        for c in columnas or ():
            _ident(c)
    nombres = ", ".join(f"'{tabla}'" for tabla, _ in tablas)
    sentencias = [
        "DO $$\n"
        "DECLARE faltan text;\n"
        "BEGIN\n"
        "    SELECT string_agg(t, ', ' ORDER BY t) INTO faltan\n"
        f"    FROM unnest(ARRAY[{nombres}]) AS t\n"
        f"    WHERE to_regclass(format('%I.%I', '{schema}', t)) IS NULL;\n"
        "    IF faltan IS NOT NULL THEN\n"
        "        RAISE EXCEPTION\n"
        f"            'tenderflow_mcp: faltan tablas visibles en {schema}: %. '\n"
        "            'Aplica antes `alembic upgrade head`.', faltan;\n"
        "    END IF;\n"
        "END $$",
        f"REVOKE ALL ON ALL TABLES IN SCHEMA {s} FROM {r}",
        f"REVOKE CREATE ON SCHEMA {s} FROM {r}",
        f"GRANT USAGE ON SCHEMA {s} TO {r}",
    ]
    for tabla, columnas in tablas:
        t = _ident(tabla)
        if columnas is not None:
            lista = ", ".join(_ident(c) for c in columnas)
            sentencias.append(f"GRANT SELECT ({lista}) ON {s}.{t} TO {r}")
        else:
            sentencias.append(f"GRANT SELECT ON {s}.{t} TO {r}")
    # Las tablas tienen RLS activo (v52): sin política el rol vería cero filas.
    # ``IF NOT EXISTS`` porque ``CREATE POLICY`` no admite ``OR REPLACE``.
    sentencias.append(
        "DO $$\n"
        "DECLARE t text;\n"
        "BEGIN\n"
        f"    FOREACH t IN ARRAY ARRAY[{nombres}] LOOP\n"
        "        IF NOT EXISTS (\n"
        "            SELECT 1 FROM pg_policies\n"
        f"            WHERE schemaname = '{schema}' AND tablename = t\n"
        f"              AND policyname = '{politica}' AND '{rol}' = ANY (roles)\n"
        "        ) THEN\n"
        "            EXECUTE format(\n"
        f"                'CREATE POLICY {politica} ON %I.%I FOR SELECT TO %I USING (true)',\n"
        f"                '{schema}', t, '{rol}'\n"
        "            );\n"
        "        END IF;\n"
        "    END LOOP;\n"
        "END $$"
    )
    return sentencias
