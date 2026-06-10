"""Verifica el entorno de desarrollo: Python, dependencias clave, DB, .env, red.

Uso: ``python scripts/doctor.py`` o ``make doctor``.

Salida con código != 0 si alguno de los checks críticos falla, para integrar
en CI o pre-flight de despliegues.
"""

from __future__ import annotations

import importlib
import os
import socket
import sqlite3
import sys
from pathlib import Path

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def _ok(msg: str) -> None:
    print(f"{GREEN}✓{RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"{YELLOW}!{RESET} {msg}")


def _err(msg: str) -> None:
    print(f"{RED}✗{RESET} {msg}")


def check_python() -> bool:
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 11):
        _err(f"Python {major}.{minor} es muy antiguo (mínimo 3.11)")
        return False
    if (major, minor) < (3, 12):
        _warn(f"Python {major}.{minor} OK (recomendado 3.12+)")
    else:
        _ok(f"Python {major}.{minor}")
    return True


def check_packages() -> bool:
    required = [
        "pandas",
        "plotly",
        "fastapi",
        "uvicorn",
        "structlog",
        "alembic",
        "argon2",
        "bcrypt",
    ]
    missing: list[str] = []
    for pkg in required:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        _err(f"Paquetes ausentes: {', '.join(missing)}")
        return False
    _ok(f"Paquetes core instalados ({len(required)})")
    return True


def check_env_file() -> bool:
    env_path = Path(".env")
    if not env_path.exists():
        _warn(".env no existe (copia de .env.example si aplica)")
        return True  # no bloqueante
    _ok(".env presente")
    return True


def check_database() -> bool:
    db_path = os.environ.get("DB_PATH", "data/licitaciones_replica.db")
    p = Path(db_path)
    if not p.exists():
        _warn(f"DB no existe en {db_path} (se creará al arrancar)")
        return True
    try:
        with sqlite3.connect(db_path) as c:
            c.execute("SELECT 1").fetchone()
        size_mb = p.stat().st_size / (1024 * 1024)
        _ok(f"DB accesible en {db_path} ({size_mb:.1f} MB)")
    except sqlite3.Error as exc:
        _err(f"Error abriendo DB {db_path}: {exc}")
        return False
    return True


def check_network() -> bool:
    try:
        socket.create_connection(("contrataciondelestado.es", 443), timeout=5).close()
        _ok("Conectividad a contrataciondelestado.es:443 OK")
        return True
    except OSError as exc:
        _warn(f"Sin acceso a contrataciondelestado.es: {exc}")
        return True  # no bloqueante


def check_writable_dirs() -> bool:
    for d in ("data", "data/downloads", "data/models", "data/metrics"):
        Path(d).mkdir(parents=True, exist_ok=True)
        if not os.access(d, os.W_OK):
            _err(f"Directorio no escribible: {d}")
            return False
    _ok("Directorios data/* escribibles")
    return True


def main() -> int:
    print("== licitaciones-sap doctor ==\n")
    results = [
        check_python(),
        check_packages(),
        check_env_file(),
        check_database(),
        check_writable_dirs(),
        check_network(),
    ]
    failed = sum(1 for r in results if not r)
    print()
    if failed == 0:
        _ok(f"Todo correcto ({len(results)} checks)")
        return 0
    _err(f"{failed}/{len(results)} checks fallaron")
    return 1


if __name__ == "__main__":
    sys.exit(main())
