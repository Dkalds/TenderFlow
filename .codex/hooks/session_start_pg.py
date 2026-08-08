"""SessionStart: provisiona el Postgres de tests en sesiones remotas.

Las sesiones remotas (Claude Code web / CI de agentes) arrancan sin Postgres
y sin ``TEST_DATABASE_URL``, así que ``tests/conftest.py`` aborta la suite
entera con ``pytest.UsageError`` y el agente que escribe el código no puede
ejecutar la red de seguridad que ese código necesita.

Este hook cierra ese hueco: arranca el cluster local si existe, crea rol y
base de tests, habilita ``pg_trgm``/``vector`` (las dos que exigen las
migraciones v50 y v56) y escribe ``TEST_DATABASE_URL`` en ``.env``, de donde
``tests/conftest.py`` la lee como fallback.

Es **best-effort y no bloqueante**: si no hay cluster, ni permisos, ni red
para instalar pgvector, el hook informa y se aparta. Nunca rompe el arranque
de la sesión — una sesión sin BD sigue siendo una sesión de trabajo válida,
solo que con los tests declarados como no ejecutados (AGENTS.md §4).

No instala el servidor: las imágenes de sesión remota ya traen
``postgresql-16``. Solo instala ``postgresql-16-pgvector`` si falta, porque
sin la extensión ``vector`` la migración v56 revienta y con ella la suite.
"""

import json
import os
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Debe coincidir con el ejemplo del error de tests/conftest.py.
DB_USER = "tenderflow"
# Credencial de un cluster local efímero que solo escucha en loopback y se
# recrea en cada sesión: no es un secreto, es el mismo par que ya aparece en
# docker-compose.yml y en el mensaje de ayuda de tests/conftest.py.
DB_PASSWORD = "tenderflow"  # noqa: S105  # pragma: allowlist secret
DB_NAME = "tenderflow"
TEST_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@localhost:5432/{DB_NAME}"

# Las que exigen db/alembic/versions/v50_pg_search_infra.py y v56_pg_documentos_pgvector.py.
REQUIRED_EXTENSIONS = ("pg_trgm", "vector")


def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    """Ejecuta *cmd* capturando salida, sin lanzar en caso de error."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False, **kwargs)


def psql_as_superuser(sql: str) -> subprocess.CompletedProcess[str]:
    """Ejecuta *sql* como el rol dueño del cluster.

    Todo el SQL que llega aquí son literales de este módulo con constantes del
    propio módulo: no hay entrada externa que pudiera inyectar.
    """
    return run(["su", "postgres", "-c", f"psql -tAc {sql!r}"])


def cluster_is_up() -> bool:
    return shutil.which("pg_isready") is not None and run(["pg_isready", "-q"]).returncode == 0


def start_cluster(notes: list[str]) -> bool:
    """Arranca el cluster local. True si quedó operativo."""
    if cluster_is_up():
        return True
    if shutil.which("pg_ctlcluster") is None:
        notes.append("no hay pg_ctlcluster: sin Postgres local que arrancar")
        return False
    result = run(["pg_ctlcluster", "16", "main", "start"])
    if not cluster_is_up():
        notes.append(f"el cluster 16/main no arrancó: {result.stderr.strip()[:200]}")
        return False
    return True


def ensure_role_and_db(notes: list[str]) -> bool:
    """Crea rol y base de tests si no existen (idempotente)."""
    role = psql_as_superuser(f"SELECT 1 FROM pg_roles WHERE rolname = '{DB_USER}'")  # noqa: S608
    if role.returncode != 0:
        notes.append(f"no se pudo consultar pg_roles: {role.stderr.strip()[:200]}")
        return False
    if "1" not in role.stdout:
        psql_as_superuser(f"CREATE ROLE {DB_USER} LOGIN PASSWORD '{DB_PASSWORD}' SUPERUSER")
    exists = psql_as_superuser(f"SELECT 1 FROM pg_database WHERE datname = '{DB_NAME}'")  # noqa: S608
    if "1" not in exists.stdout:
        psql_as_superuser(f"CREATE DATABASE {DB_NAME} OWNER {DB_USER}")
    return True


def ensure_extensions(notes: list[str]) -> None:
    """Habilita pg_trgm y vector; instala pgvector por apt si falta.

    ``_materialize_schema_ddl`` filtra los ``CREATE EXTENSION`` del dump a
    propósito, así que las extensiones tienen que existir ya en la base.
    """
    share = pathlib.Path("/usr/share/postgresql/16/extension/vector.control")
    if not share.exists() and shutil.which("apt-get") is not None:
        installed = run(["apt-get", "install", "-y", "postgresql-16-pgvector"])
        if installed.returncode != 0:
            notes.append(
                "no se pudo instalar postgresql-16-pgvector (¿sin red?): "
                "la migración v56 fallará y con ella la suite"
            )
    env = {**os.environ, "PGPASSWORD": DB_PASSWORD}
    for ext in REQUIRED_EXTENSIONS:
        created = run(
            [
                "psql",
                "-h",
                "127.0.0.1",
                "-U",
                DB_USER,
                "-d",
                DB_NAME,
                "-c",
                f"CREATE EXTENSION IF NOT EXISTS {ext}",
            ],
            env=env,
        )
        if created.returncode != 0:
            notes.append(f"no se pudo crear la extensión {ext}: {created.stderr.strip()[:160]}")


def persist_test_url() -> None:
    """Escribe TEST_DATABASE_URL en .env (gitignored) si no está ya."""
    env_file = ROOT / ".env"
    existing = env_file.read_text(encoding="utf-8") if env_file.is_file() else ""
    if "TEST_DATABASE_URL=" in existing:
        return
    prefix = "" if existing.endswith("\n") or not existing else "\n"
    env_file.write_text(f"{existing}{prefix}TEST_DATABASE_URL={TEST_URL}\n", encoding="utf-8")


def emit(message: str) -> None:
    """Devuelve contexto al agente por el protocolo de hooks."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": message,
                }
            }
        )
    )


def main() -> None:
    notes: list[str] = []
    if not start_cluster(notes) or not ensure_role_and_db(notes):
        emit(
            "Postgres de tests NO disponible en esta sesión: "
            + "; ".join(notes)
            + ". La suite no se puede ejecutar; reportá los tests como no ejecutados "
            "(AGENTS.md §4) en vez de darlos por verdes."
        )
        return
    ensure_extensions(notes)
    persist_test_url()
    message = (
        f"Postgres de tests listo ({TEST_URL}); TEST_DATABASE_URL escrita en .env. "
        "`make test-unit` y `make check` se pueden ejecutar en esta sesión."
    )
    if notes:
        message += " Avisos: " + "; ".join(notes)
    emit(message)


try:
    main()
except Exception as exc:  # un hook nunca debe romper el arranque de la sesión
    emit(f"El hook de Postgres falló ({exc}); la suite puede no ser ejecutable.")
