"""Rotación de API Keys con grace period (B6).

Crea una nueva API Key, marca la anterior como expirada en N días, y
devuelve el nuevo token al operador.

Uso::

    python scripts/rotate_api_keys.py --name mi-cliente --grace-days 7

Salida:
    NEW_API_KEY=xxx... (guardar de forma segura)
    OLD_KEY expira el 2026-05-22T12:00:00+00:00

Después de ``grace-days``, la clave antigua dejará de validar (el middleware
`require_api_key` ya consulta `expires_at`).
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta

from api.auth import _hash_key, create_api_key
from db.database import connect


def rotate(name: str, grace_days: int) -> int:
    """Rota la(s) clave(s) activa(s) con ``name`` y crea una nueva.

    Args:
        name: Nombre lógico de la clave (e.g. "mi-cliente").
        grace_days: Días que la clave anterior seguirá siendo válida.

    Returns:
        Exit code (0 OK, 1 si no había clave previa pero se crea una nueva).
    """
    expires_at = (datetime.now(UTC) + timedelta(days=grace_days)).isoformat()

    # Marcar las claves activas existentes con ese nombre como expirando
    with connect() as c:
        cols = {row[1] for row in c.execute("PRAGMA table_info(api_keys)").fetchall()}
        if "expires_at" not in cols:
            print(
                "ERROR: la columna 'expires_at' no existe. Ejecuta: alembic upgrade head",
                file=sys.stderr,
            )
            return 2
        cur = c.execute(
            "UPDATE api_keys SET expires_at = ? "
            "WHERE name = ? AND is_active = 1 AND (expires_at IS NULL OR expires_at > ?)",
            (expires_at, name, expires_at),
        )
        rotated = cur.rowcount

    new_token = create_api_key(name)

    print(f"NEW_API_KEY={new_token}")
    print(f"NEW_API_KEY_HASH={_hash_key(new_token)}")
    if rotated:
        print(f"OLD_KEYS_EXPIRES_AT={expires_at}  (afectadas: {rotated})")
    else:
        print("(sin claves previas con ese nombre — primera emisión)")

    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--name", required=True, help="Nombre lógico de la clave")
    p.add_argument(
        "--grace-days",
        type=int,
        default=7,
        help="Días que la clave anterior seguirá siendo válida (default: 7)",
    )
    args = p.parse_args()

    if args.grace_days < 0:
        print("--grace-days debe ser >= 0", file=sys.stderr)
        return 2

    return rotate(args.name, args.grace_days)


if __name__ == "__main__":
    sys.exit(main())
