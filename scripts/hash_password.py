#!/usr/bin/env python3
"""Genera un hash seguro para usar como DASHBOARD_PASSWORD_HASH en .env.

Por defecto usa **argon2id** (más seguro que bcrypt). Si argon2-cffi no está
instalado, hace fallback a bcrypt.

Uso:
    python scripts/hash_password.py
    python scripts/hash_password.py "mi_contraseña"
    python scripts/hash_password.py --algo bcrypt "mi_contraseña"
"""

from __future__ import annotations

import getpass
import sys


def hash_argon2(password: str) -> str:
    from argon2 import PasswordHasher

    ph = PasswordHasher(
        time_cost=3,       # iteraciones
        memory_cost=65536, # 64 MB
        parallelism=2,
        hash_len=32,
        salt_len=16,
    )
    return ph.hash(password)


def hash_bcrypt(password: str) -> str:
    import bcrypt

    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Genera hash de contraseña para .env")
    parser.add_argument("password", nargs="?", help="Contraseña (si no se da, se pide interactivo)")
    parser.add_argument(
        "--algo",
        choices=["argon2", "bcrypt"],
        default="argon2",
        help="Algoritmo de hash (default: argon2)",
    )
    args = parser.parse_args()

    if args.password:
        password = args.password
    else:
        password = getpass.getpass("Contraseña: ")
        confirm = getpass.getpass("Confirmar:   ")
        if password != confirm:
            print("Las contraseñas no coinciden.", file=sys.stderr)
            sys.exit(1)

    if args.algo == "argon2":
        try:
            hashed = hash_argon2(password)
        except ImportError:
            print(
                "argon2-cffi no instalado. Usando bcrypt como fallback.",
                file=sys.stderr,
            )
            hashed = hash_bcrypt(password)
    else:
        hashed = hash_bcrypt(password)

    print("\nAñade esta línea a tu .env:\n")
    print(f"DASHBOARD_PASSWORD_HASH={hashed}")


if __name__ == "__main__":
    main()
