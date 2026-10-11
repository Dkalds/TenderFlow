# Entorno local en Windows: los controles corren en WSL

En un host Windows los controles del repo no se pueden ejecutar tal cual:

- La suite de integración necesita `pg_dump` en el PATH (`tests/conftest.py`
  materializa el esquema con él) y no hay cliente de Postgres.
- `make` y `jq` no están en el PATH de Git Bash.
- El `.venv` de la raíz principal lo comparten todos los worktrees, aunque sus
  lockfiles difieran, y se queda atrás respecto a `requirements-dev.txt`.
- Application Control bloquea ruedas nativas recién publicadas: con los pines
  del lockfile, `pandas` y `psycopg-binary` no llegan a importar.

La salida es una distro Ubuntu de WSL2 con Postgres nativo. Dos scripts:

| Script | Cuándo | Qué hace |
|---|---|---|
| [`scripts/dev/wsl_setup.sh`](../../scripts/dev/wsl_setup.sh) | Una vez, como root | Instala Postgres 16 (PGDG) con `pgvector`, `make`, `jq` y `uv`; crea el rol `tenderflow` |
| [`scripts/dev/wsl_run.sh`](../../scripts/dev/wsl_run.sh) | Cada vez | Corre un comando del repo con el entorno del lockfile y una base de tests propia del checkout |

## Alta, una vez por máquina

Desde Git Bash, en la raíz del repo (o de cualquier worktree):

```bash
MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu -u root --cd "$(cygpath -w "$PWD")" -e bash scripts/dev/wsl_setup.sh
```

Es idempotente. Postgres 16 y no el de la distro, por paridad con CI
(`pgvector/pgvector:pg16`).

## Uso

```bash
bash scripts/dev/wsl_run.sh make check
```

```bash
bash scripts/dev/wsl_run.sh pytest tests/test_healthcheck.py -q
```

Vale desde Git Bash (se relanza dentro de WSL) y desde una shell de la distro.
Lo que el envoltorio deja preparado antes de ejecutar el comando:

- **Entorno virtual por lockfile.** `uv pip sync --require-hashes
  requirements-dev.txt` más las dependencias del extra `[pliegos]`, como CI.
  Se guarda en `~/.cache/tenderflow/venvs/<huella>` dentro de la distro, con la
  huella de `requirements-dev.txt` y `pyproject.toml`: dos worktrees con el
  mismo lock comparten entorno, y uno que lo cambie estrena el suyo. Quedan los
  tres últimos.
- **Una base de tests por checkout**, `tf_<huella de la ruta>` en
  `localhost:5432`, con `pg_trgm`, `unaccent` y `vector`. Dos sesiones de pytest
  contra la misma base se pisan (`_pg_schema_ddl` vacía `public` sin lock entre
  procesos); con una base por worktree, varias sesiones a la vez no chocan.
- **Git operativo en un worktree creado desde Windows**: exporta `GIT_DIR` y
  `GIT_WORK_TREE`, porque el `.git` del worktree apunta a una ruta `C:/…` que
  el git de la distro no sabe abrir. Sin eso fallan los ratchets y `make status`.
- **Cachés fuera de `/mnt/c`** (bytecode, mypy, ruff): escribir ahí es lo que
  hace lento a WSL sobre un checkout de Windows.
- `ENV=dev`, `PYTHONPATH` en la raíz del checkout y `TEST_DATABASE_URL`.

## Medido el 2026-10-11

Ubuntu 26.04 en WSL 2.6.3, 24 hilos, checkout en `/mnt/c`:

| Qué | Tiempo |
|---|---|
| `wsl_setup.sh` desde una distro vacía | unos 2 min |
| Primer `wsl_run.sh` con un lockfile nuevo (crear el entorno) | 9 s con la caché de uv, ~1 min sin ella |
| `ruff check .` + `ruff format --check .` | segundos |
| `mypy .` (1.176 ficheros, caché fría) | 51 s |
| `pytest tests/ -m "(unit or integration) and not slow" -n 6` | 34 min 33 s: 10.042 pasan, 4 xfail, 0 fallos |

La pasada completa se midió con el equipo cargado (la VM tirando de swap, ver
abajo): es un techo, no lo que tarda en una máquina desahogada. Los backends de
Postgres pasaban el tiempo en espera de disco con el DDL de cada test; apagar
`fsync` en el cluster se probó ese día y no cambió nada medible (el mismo
subconjunto de 82 tests, 97 s antes y 124 s después), así que no se dejó puesto.

## Límites conocidos

- **Memoria.** WSL reserva por defecto hasta la mitad de la RAM del host y no
  devuelve enseguida la caché de disco. Con el equipo cargado (varias sesiones
  de agente a la vez, Docker Desktop) la VM dejó de aceptar conexiones durante
  unos minutos el 2026-10-11 (`Wsl/Service/0x8007274c`) y volvió sola. Lo que
  lo acota es un `%UserProfile%\.wslconfig` con un techo y reclamación de
  memoria; aplicarlo exige `wsl --shutdown`, que corta Docker Desktop y
  cualquier shell abierta en la distro, así que es decisión de quien usa la
  máquina:

  ```ini
  [wsl2]
  memory=8GB

  [experimental]
  autoMemoryReclaim=gradual
  ```

- **Paralelismo.** `-n auto` lanza un worker por hilo (24 en esta máquina) y
  cada uno carga pandas y scikit-learn: con el techo de memoria de arriba,
  mejor `-n 6`.
- **No editar código mientras corre la suite.** Los tests que usan
  `inspect.getsource` leen el fichero nuevo con los números de línea del módulo
  ya importado.
- **Postgres tras reiniciar la distro.** Lo arranca systemd. Si `wsl_run.sh`
  dice que no responde: `sudo pg_ctlcluster 16 main start`.
- **El frontend no pasa por aquí.** `web/` sigue con el Node del host
  (`npm ci`, `npx next build`).

## Relación con otros caminos

- Las sesiones remotas (Claude Code web, CI de agentes) no usan esto: su
  Postgres lo provisiona `.claude/hooks/session_start_pg.py`.
- `.devcontainer/` sigue valiendo para Codespaces.
- La receta anterior —un contenedor `python:3.13-slim` con `socat` hacia un
  `pgvector/pgvector:pg16`— queda como alternativa donde Docker Desktop sea
  fiable; en esta máquina no lo es.
