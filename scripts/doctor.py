"""Verifica el entorno de desarrollo: Python, dependencias clave, DB, .env, red.

Uso: ``python scripts/doctor.py`` o ``make doctor``.

Salida con código != 0 si alguno de los checks críticos falla, para integrar
en CI o pre-flight de despliegues.

Checks disponibles:
  - Python >= 3.11
  - Paquetes core instalados
  - .env presente
  - DATABASE_URL alcanzable (Postgres) o SQLite accesible (legacy)
  - alembic current == head (warn si hay migraciones pendientes)
  - predicciones_baja no vacía (warn → make seed --with-predicciones)
  - REDIS_URL ping (warn si no responde, nunca error bloqueante)
  - web/src/generated/api.d.ts existe (warn si falta)
  - Directorios data/* escribibles
  - Conectividad a contrataciondelestado.es (warn)
"""

from __future__ import annotations

import importlib
import os
import socket
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlsplit

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
    """Verifica DATABASE_URL (Postgres) o la BD SQLite legacy."""
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url:
        # Postgres / Supabase
        try:
            import importlib.util

            if importlib.util.find_spec("psycopg") is None:
                _warn("DATABASE_URL definida pero psycopg no instalado (F3 pendiente)")
                return True
            import psycopg  # type: ignore[import-not-found]

            with psycopg.connect(database_url, connect_timeout=5) as conn:
                conn.execute("SELECT 1").fetchone()
            # No mostrar el DSN crudo: user:pass viajarían en claro al output
            # (terminal, logs de CI, capturas compartidas). Solo host/puerto/db.
            parsed = urlsplit(database_url)
            safe_target = f"{parsed.hostname}:{parsed.port or 5432}{parsed.path}"
            _ok(f"DATABASE_URL alcanzable ({safe_target})")
        except Exception as exc:
            _err(f"DATABASE_URL no alcanzable: {exc}")
            return False
    else:
        # SQLite legacy
        db_path = os.environ.get("DB_PATH", "data/licitaciones_replica.db")
        p = Path(db_path)
        if not p.exists():
            _warn(f"DB no existe en {db_path} (se creará al arrancar o con `make seed`)")
            return True
        try:
            with sqlite3.connect(db_path) as c:
                c.execute("SELECT 1").fetchone()
            size_mb = p.stat().st_size / (1024 * 1024)
            _ok(f"DB SQLite accesible en {db_path} ({size_mb:.1f} MB)")
        except sqlite3.Error as exc:
            _err(f"Error abriendo DB {db_path}: {exc}")
            return False
    return True


def check_alembic_head() -> bool:
    """Verifica que la BD está en alembic head (warn si hay migraciones pendientes)."""
    try:
        import subprocess

        result = subprocess.run(
            [sys.executable, "-m", "alembic", "current"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = result.stdout + result.stderr
        if "head" in output:
            _ok("Alembic: BD en head")
        elif result.returncode != 0:
            _warn(f"Alembic no disponible: {output.strip()[:80]}")
        else:
            _warn(
                "Alembic: hay migraciones pendientes → ejecuta `alembic upgrade head` "
                "o `make migrate`"
            )
    except Exception as exc:
        _warn(f"No se pudo verificar alembic: {exc}")
    return True  # nunca bloqueante


def check_predicciones_baja() -> bool:
    """Verifica que predicciones_baja tiene filas (warn si vacía)."""
    database_url = os.environ.get("DATABASE_URL", "")
    db_path = os.environ.get("DB_PATH", "data/licitaciones_replica.db")

    try:
        if database_url:
            import importlib.util

            if importlib.util.find_spec("psycopg") is None:
                return True  # no podemos verificar sin psycopg
            import psycopg  # type: ignore[import-not-found]

            with psycopg.connect(database_url, connect_timeout=5) as conn:
                row = conn.execute("SELECT COUNT(*) FROM predicciones_baja").fetchone()
                count = int(row[0]) if row else 0
        else:
            if not Path(db_path).exists():
                return True  # DB no creada aún
            with sqlite3.connect(db_path) as c:
                row = c.execute("SELECT COUNT(*) FROM predicciones_baja").fetchone()
                count = int(row[0]) if row else 0

        if count == 0:
            _warn(
                "predicciones_baja está vacía → la UI mostrará 404 en /predicciones. "
                "Ejecuta: python scripts/seed_dev.py --with-predicciones"
            )
        else:
            _ok(f"predicciones_baja: {count} filas")
    except Exception as exc:
        _warn(f"No se pudo verificar predicciones_baja: {exc}")
    return True  # nunca bloqueante


def check_redis() -> bool:
    """Ping a REDIS_URL si está configurado (warn si no responde)."""
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        _ok("REDIS_URL no configurado (opt-in, OK en dev local)")
        return True
    try:
        import urllib.parse
        import urllib.request

        parsed = urllib.parse.urlparse(redis_url)
        host = parsed.hostname or ""
        if host.endswith(".upstash.io"):
            token = parsed.password or ""
            url = f"https://{host}/PING"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})  # noqa: S310
            with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
                body = resp.read().decode()
            if "PONG" in body:
                _ok(f"Redis (Upstash) responde en {host}")
                return True
            _warn(f"Redis (Upstash) respuesta inesperada: {body[:40]}")
            return True
        import redis as _redis  # type: ignore[import-not-found]

        _redis.from_url(redis_url, socket_connect_timeout=2).ping()
        _ok(f"Redis responde en {host}")
    except Exception as exc:
        _warn(f"Redis no responde ({exc}) — funcionalidad degradada en dev, no bloqueante")
    return True  # nunca bloqueante


def check_frontend_types() -> bool:
    """Verifica que web/src/generated/api.d.ts existe (warn si falta)."""
    target = Path("web/src/generated/api.d.ts")
    if not target.exists():
        _warn(
            "web/src/generated/api.d.ts no existe → el frontend puede fallar en typecheck. "
            "Ejecuta: cd web && npm run codegen:best-effort  (o arranca la API primero)"
        )
    else:
        _ok("web/src/generated/api.d.ts presente")
    return True  # nunca bloqueante


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
    print("== Tenderflow doctor ==\n")
    results = [
        check_python(),
        check_packages(),
        check_env_file(),
        check_database(),
        check_alembic_head(),
        check_predicciones_baja(),
        check_redis(),
        check_frontend_types(),
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
