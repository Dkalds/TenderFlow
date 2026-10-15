#!/usr/bin/env python3
"""Genera ``scripts/setup_pg_role_mcp.sql``: el rol de solo lectura del MCP interno.

La política (qué tablas y columnas ve el rol) vive en ``mcp_server/catalogo.py``;
este script solo la vuelca a SQL para que un humano con el rol dueño la ejecute.
No toca ninguna base de datos. Mismo patrón que ``gen_rfc_index.py``: el
fichero es un artefacto calculado y ``--check`` falla si está desfasado.

Uso::

    python scripts/gen_mcp_grants.py            # reescribe el SQL
    python scripts/gen_mcp_grants.py --check    # sale con 1 si está desfasado
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_server.catalogo import ROL_MCP, sentencias_grants, sentencias_rol  # noqa: E402

SALIDA = _REPO_ROOT / "scripts" / "setup_pg_role_mcp.sql"

_CABECERA = """\
-- GENERADO por scripts/gen_mcp_grants.py a partir de mcp_server/catalogo.py.
-- No lo edites a mano: cambia el catálogo y regenera con
--   python scripts/gen_mcp_grants.py
-- (`--check` falla en CI/tests si este fichero está desfasado).
--
-- Rol `tenderflow_mcp` del MCP interno de solo lectura: SELECT sobre las tablas
-- de datos de mercado y de cliente del catálogo, nada sobre credenciales ni
-- secretos (api_keys, sessions, TOTP, tokens, tablas OAuth del MCP, cadena de
-- auditoría), y sin columnas con hashes de contraseña o secretos de webhook.
-- Transacciones de solo lectura, timeouts y 5 conexiones como máximo.
--
-- Cómo ejecutar (acción manual del usuario — gate secrets+ops, AGENTS.md §6):
--   1. Generar una password fuerte: openssl rand -base64 32
--   2. Sustituir el placeholder <GENERAR_PASSWORD_FUERTE> abajo con esa password.
--   3. Ejecutar contra Supabase con el rol ADMIN (dueño del schema, DATABASE_ADMIN_URL):
--        psql "$DATABASE_ADMIN_URL" -f scripts/setup_pg_role_mcp.sql
--   4. Construir MCP_DATABASE_URL con este rol:
--        postgresql://tenderflow_mcp:<password>@<host>:5432/postgres?sslmode=verify-full
--
-- Idempotente: seguro de re-ejecutar. Los GRANT parten de un REVOKE completo, así
-- que una tabla o columna que el catálogo oculte después pierde el acceso.
-- Fallo cerrado: no hay ALTER DEFAULT PRIVILEGES; una tabla nueva es invisible
-- para este rol hasta clasificarla en el catálogo y regenerar este fichero.

-- ── 1. Rol ──────────────────────────────────────────────────────────────────

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{rol}') THEN
        CREATE ROLE {rol} LOGIN PASSWORD '<GENERAR_PASSWORD_FUERTE>';  -- pragma: allowlist secret
    END IF;
END $$;

"""


def generar() -> str:
    """Contenido completo y determinista del SQL del rol."""
    partes = [_CABECERA.format(rol=ROL_MCP)]
    partes.append(
        "-- ── 2. Límites del rol ──────────────────────────────────────────────────────\n"
    )
    partes.extend(f"{s};\n" for s in sentencias_rol(ROL_MCP))
    partes.append(
        "\n-- ── 3. Privilegios de lectura y política RLS ───────────────────────────────\n"
    )
    partes.extend(f"{s};\n" for s in sentencias_grants(ROL_MCP, "public"))
    return "".join(partes)


def main(argv: list[str]) -> int:
    esperado = generar()
    if "--check" in argv:
        actual = SALIDA.read_text(encoding="utf-8") if SALIDA.exists() else ""
        if actual == esperado:
            return 0
        diff = difflib.unified_diff(
            actual.splitlines(), esperado.splitlines(), "commiteado", "generado", lineterm=""
        )
        print("\n".join(list(diff)[:40]))
        print(
            "scripts/setup_pg_role_mcp.sql está desfasado: "
            "ejecuta `python scripts/gen_mcp_grants.py`.",
            file=sys.stderr,
        )
        return 1
    SALIDA.write_text(esperado, encoding="utf-8")
    print(f"Escrito {SALIDA.relative_to(_REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
