"""Rotación de API Keys con grace period (B6).

Crea una nueva API Key, marca la anterior como expirada en N días, y
devuelve el nuevo token al operador.

Uso::

    python scripts/rotate_api_keys.py --name mi-cliente --user-id 42 --grace-days 7

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
from db.repositories.api_keys import ApiKeyRepository


def rotate(name: str, user_id: int, grace_days: int, scopes: str = "*") -> int:
    """Rota la(s) clave(s) activa(s) con ``name`` y crea una nueva.

    Args:
        name: Nombre lógico de la clave (e.g. "mi-cliente").
        user_id: Propietario de las claves a rotar y de la nueva clave.
        grace_days: Días que la clave anterior seguirá siendo válida.
        scopes: Scopes para una primera emisión; en una rotación conserva los existentes.

    Returns:
        Exit code (0 OK, 1 si no había clave previa pero se crea una nueva).
    """
    expires_at = (datetime.now(UTC) + timedelta(days=grace_days)).isoformat()

    # Marcar las claves activas existentes con ese nombre como expirando
    marcadas = ApiKeyRepository().expirar_por_nombre(name, user_id, expires_at)
    if marcadas is None:
        print(
            "ERROR: faltan columnas de seguridad. Ejecuta: alembic upgrade head",
            file=sys.stderr,
        )
        return 2
    scopes_previos, rotated = marcadas
    effective_scopes = scopes_previos if scopes_previos is not None else scopes

    new_token = create_api_key(name, scopes=effective_scopes, user_id=user_id)

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
    p.add_argument("--user-id", type=int, required=True, help="ID del propietario de la clave")
    p.add_argument("--scopes", default="*", help="Scopes para una primera emisión")
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

    return rotate(args.name, args.user_id, args.grace_days, args.scopes)


if __name__ == "__main__":
    sys.exit(main())
