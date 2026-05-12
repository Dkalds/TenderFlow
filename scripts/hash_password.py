#!/usr/bin/env python3
"""Genera un hash bcrypt para usar como DASHBOARD_PASSWORD_HASH en .env.

Uso:
    python scripts/hash_password.py
    python scripts/hash_password.py "mi_contraseña"
"""

from __future__ import annotations

import getpass
import sys

import bcrypt


def main() -> None:
    if len(sys.argv) > 1:
        password = sys.argv[1]
    else:
        password = getpass.getpass("Contraseña: ")
        confirm = getpass.getpass("Confirmar:   ")
        if password != confirm:
            print("Las contraseñas no coinciden.", file=sys.stderr)  # noqa: T201
            sys.exit(1)

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    print(f"\nAñade esta línea a tu .env:\n")  # noqa: T201
    print(f"DASHBOARD_PASSWORD_HASH={hashed}")  # noqa: T201


if __name__ == "__main__":
    main()
