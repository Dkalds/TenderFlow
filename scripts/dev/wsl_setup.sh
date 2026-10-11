#!/usr/bin/env bash
# Prepara una distro Ubuntu de WSL2 para correr los controles del repo en una
# máquina Windows. Se ejecuta UNA vez, como root, desde la raíz del repo:
#
#     wsl.exe -d Ubuntu -u root --cd "<ruta del repo>" -e bash scripts/dev/wsl_setup.sh
#
# Instala lo que el host Windows no tiene y `tests/conftest.py` exige: un
# Postgres con `pg_dump` en el PATH, `pgvector`, `make`, `jq` y `uv`. Después,
# `scripts/dev/wsl_run.sh` corre cualquier comando del Makefile ahí dentro.
#
# Es idempotente: volver a ejecutarlo no rompe nada y repara lo que falte.
#
# Postgres 16 y no el de la distro, por paridad con CI (`pgvector/pgvector:pg16`
# en `.github/workflows/ci.yml`) y con el hook de las sesiones remotas
# (`.claude/hooks/session_start_pg.py`). Sale del repositorio PGDG, que es de
# donde Ubuntu deja instalar una versión mayor distinta de la suya.
set -euo pipefail

PG_MAJOR="${PG_MAJOR:-16}"
# Mismo par que docker-compose.yml, CI y el hook de sesión: un cluster local
# que solo escucha en loopback, no una credencial real.
DB_USER="tenderflow"
DB_PASSWORD="tenderflow" # pragma: allowlist secret
DB_NAME="tenderflow"

morir() {
    echo "wsl_setup: $*" >&2
    exit 1
}

[[ "$(uname -s)" == "Linux" ]] || morir "esto corre dentro de WSL, no en el host Windows"
[[ "${EUID}" -eq 0 ]] || morir "hace falta root: wsl.exe -u root … -e bash scripts/dev/wsl_setup.sh"
command -v apt-get >/dev/null || morir "solo distros con apt (Ubuntu/Debian)"

export DEBIAN_FRONTEND=noninteractive

echo "wsl_setup: paquetes base"
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
    ca-certificates curl git jq make postgresql-common >/dev/null

# Sin tubería a `grep -q`: con `pipefail`, grep cierra al primer acierto,
# apt-cache muere de SIGPIPE y el acierto se lee como fallo.
hay_candidato() {
    local salida
    salida="$(apt-cache policy "$1")"
    [[ "$salida" =~ Candidate:\ [0-9] ]]
}

if ! hay_candidato "postgresql-${PG_MAJOR}"; then
    echo "wsl_setup: repositorio PGDG"
    # El script viaja dentro de `postgresql-common`: no se descarga nada suelto.
    /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y >/dev/null
    apt-get update -qq
fi
hay_candidato "postgresql-${PG_MAJOR}" ||
    morir "PGDG no publica postgresql-${PG_MAJOR} para esta distro; probá con PG_MAJOR=<otra>"

echo "wsl_setup: postgresql-${PG_MAJOR} + pgvector"
apt-get install -y -qq --no-install-recommends \
    "postgresql-${PG_MAJOR}" "postgresql-client-${PG_MAJOR}" "postgresql-${PG_MAJOR}-pgvector" >/dev/null

pg_isready -q || pg_ctlcluster "${PG_MAJOR}" main start || true
for _ in 1 2 3 4 5 6 7 8 9 10; do
    pg_isready -q && break
    sleep 1
done
pg_isready -q || morir "el cluster ${PG_MAJOR}/main no arrancó (pg_lsclusters para ver por qué)"

psql_super() {
    runuser -u postgres -- psql -v ON_ERROR_STOP=1 -tA "$@"
}

# SUPERUSER porque `wsl_run.sh` crea una base por checkout y sus extensiones.
if [[ "$(psql_super -c "SELECT 1 FROM pg_roles WHERE rolname = '${DB_USER}'")" != "1" ]]; then
    psql_super -c "CREATE ROLE ${DB_USER} LOGIN SUPERUSER PASSWORD '${DB_PASSWORD}'" >/dev/null
fi
if [[ "$(psql_super -c "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'")" != "1" ]]; then
    psql_super -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}" >/dev/null
fi

if ! command -v uv >/dev/null; then
    echo "wsl_setup: uv"
    # Instalador oficial (https://docs.astral.sh/uv/); `UV_UNMANAGED_INSTALL`
    # lo deja en /usr/local/bin sin tocar el perfil de ningún usuario.
    curl -LsSf https://astral.sh/uv/install.sh |
        env UV_UNMANAGED_INSTALL=/usr/local/bin sh >/dev/null 2>&1
fi
command -v uv >/dev/null || morir "uv no quedó instalado"

echo "wsl_setup: listo — $(psql --version | head -1), $(uv --version)"
echo "wsl_setup: siguiente paso, ya sin root: bash scripts/dev/wsl_run.sh make check"
