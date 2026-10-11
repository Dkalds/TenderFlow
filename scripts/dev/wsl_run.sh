#!/usr/bin/env bash
# Corre un comando del repo dentro de WSL, con las dependencias del lockfile y
# un Postgres de tests propio de este checkout. Desde la raíz del repo:
#
#     bash scripts/dev/wsl_run.sh make check
#     bash scripts/dev/wsl_run.sh pytest tests/test_api_health.py -q
#
# Vale igual desde Git Bash en Windows (se relanza a sí mismo dentro de WSL) que
# desde una shell de la distro. Requiere haber corrido antes, una vez y como
# root, `scripts/dev/wsl_setup.sh`.
#
# Por qué existe: en el host Windows la suite de integración no corre
# (`tests/conftest.py` necesita `pg_dump`), `make` y `jq` no están en el PATH, y
# el `.venv` de la raíz principal lo comparten todos los worktrees aunque sus
# lockfiles difieran. Aquí:
#
# - El entorno virtual sale de `requirements-dev.txt` con hashes, como en CI, y
#   se guarda por huella del lockfile: dos worktrees con el mismo lock comparten
#   entorno, y uno que lo cambie estrena el suyo sin pisar el de los demás.
# - Cada checkout tiene su base de tests. `_pg_schema_ddl` vacía `public` sin
#   lock entre procesos, así que dos sesiones de pytest contra la misma base se
#   pisan; con varias sesiones abiertas a la vez eso es lo normal, no el caso
#   raro.
# - Las cachés (bytecode, mypy, ruff) viven en el disco de la distro: escribirlas
#   en `/mnt/c` es lo que hace lento a WSL sobre un checkout de Windows.
set -euo pipefail

morir() {
    echo "wsl_run: $*" >&2
    exit 1
}

case "$(uname -s)" in
MINGW* | MSYS* | CYGWIN*)
    command -v wsl.exe >/dev/null || morir "no hay wsl.exe en el PATH"
    # MSYS_NO_PATHCONV: sin él Git Bash convierte en ruta de Windows cualquier
    # argumento que empiece por `/`.
    MSYS_NO_PATHCONV=1 exec wsl.exe -d "${TF_WSL_DISTRO:-Ubuntu}" \
        --cd "$(cygpath -w "$PWD")" -e bash scripts/dev/wsl_run.sh "$@"
    ;;
esac

[[ $# -gt 0 ]] || morir "uso: bash scripts/dev/wsl_run.sh <comando> [args…]"
[[ "${EUID}" -ne 0 ]] || morir "sin root: el entorno virtual se guarda en el home del usuario"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"

for herramienta in uv psql pg_dump make; do
    command -v "$herramienta" >/dev/null ||
        morir "falta ${herramienta}: wsl.exe -u root … -e bash scripts/dev/wsl_setup.sh"
done
pg_isready -q -h localhost ||
    morir "Postgres no responde en localhost:5432: sudo pg_ctlcluster 16 main start"

CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/tenderflow"
HUELLA_LOCK="$(cat requirements-dev.txt pyproject.toml | sha256sum | cut -c1-12)"
HUELLA_REPO="$(printf '%s' "$REPO" | sha256sum | cut -c1-10)"
VENV="${CACHE}/venvs/${HUELLA_LOCK}"
mkdir -p "${CACHE}/venvs"

# ── Entorno virtual por lockfile ──────────────────────────────────────────
# `flock`: dos sesiones que estrenan el mismo lock a la vez no lo construyen
# dos veces ni se lo encuentran a medias. La marca `.completo` distingue un
# entorno terminado de uno que se quedó a mitad de instalación.
(
    flock 9
    if [[ ! -f "${VENV}/.completo" ]]; then
        echo "wsl_run: creando el entorno ${HUELLA_LOCK} (solo la primera vez con este lockfile)" >&2
        rm -rf "$VENV"
        uv venv --quiet --python 3.13 "$VENV"
        uv pip sync --quiet --python "${VENV}/bin/python" --require-hashes requirements-dev.txt
        # Lo que CI añade con `pip install -e ".[pliegos]"`. Solo las
        # dependencias del extra: el proyecto no se instala, porque el entorno
        # se comparte entre checkouts y un editable lo ataría a uno.
        uv pip install --quiet --python "${VENV}/bin/python" \
            --constraint requirements-dev.txt -r pyproject.toml --extra pliegos
        touch "${VENV}/.completo"
        # Los entornos de lockfiles viejos no se usan más: quedan los tres últimos.
        find "${CACHE}/venvs" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' |
            sort -rn | tail -n +4 | cut -d' ' -f2- | xargs -r rm -rf
    fi
) 9>"${CACHE}/venvs/.lock"

# ── Base de tests de este checkout ────────────────────────────────────────
# Mismo par que docker-compose.yml y CI: cluster local en loopback, no un secreto.
export PGPASSWORD="tenderflow" # pragma: allowlist secret
BASE="tf_${HUELLA_REPO}"
psql_local() {
    # client_min_messages: sin él, cada CREATE … IF NOT EXISTS escribe un NOTICE.
    PGOPTIONS="-c client_min_messages=warning"         psql -h localhost -U tenderflow -v ON_ERROR_STOP=1 -qtA "$@"
}
if [[ "$(psql_local -d postgres -c "SELECT 1 FROM pg_database WHERE datname = '${BASE}'")" != "1" ]]; then
    psql_local -d postgres -c "CREATE DATABASE ${BASE}" >/dev/null
fi
# `_materialize_schema_ddl` filtra los CREATE EXTENSION del dump: tienen que
# existir ya en la base (v50 pide pg_trgm; v56, vector; v87, unaccent).
psql_local -d "$BASE" -c "CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS unaccent; CREATE EXTENSION IF NOT EXISTS vector" >/dev/null
unset PGPASSWORD

# ── Git en un worktree creado desde Windows ───────────────────────────────
# Su `.git` es un fichero con la ruta de Windows del directorio administrativo
# (`gitdir: C:/…`), que el git de la distro no sabe abrir. Sin esto fallan los
# tests y scripts que llaman a git (los ratchets, `make status`).
if [[ -f .git ]]; then
    gitdir="$(sed -n 's/^gitdir: //p' .git)"
    if [[ "$gitdir" =~ ^[A-Za-z]:[\\/] ]]; then
        GIT_DIR="$(wslpath -u "$gitdir")"
        export GIT_DIR GIT_WORK_TREE="$REPO"
    fi
fi

export VIRTUAL_ENV="$VENV"
export PATH="${VENV}/bin:${PATH}"
export PYTHONPATH="${REPO}${PYTHONPATH:+:${PYTHONPATH}}"
export PYTHONPYCACHEPREFIX="${CACHE}/pycache"
export MYPY_CACHE_DIR="${CACHE}/mypy/${HUELLA_REPO}"
export RUFF_CACHE_DIR="${CACHE}/ruff/${HUELLA_REPO}"
export ENV="${ENV:-dev}"
export TEST_DATABASE_URL="${TEST_DATABASE_URL:-postgresql://tenderflow:tenderflow@localhost:5432/${BASE}}" # pragma: allowlist secret

exec "$@"
