# AGENTS.md

Fuente canónica de instrucciones para todos los agentes (Claude Code, Copilot, OpenCode, Cursor, etc.). `CLAUDE.md` y `.github/copilot-instructions.md` referencian este archivo y solo añaden overrides específicos de su plataforma. **Si editás reglas, editá aquí.**

Guía completa de navegación, workflows y patrones: [docs/AGENT_PLAYBOOK.md](docs/AGENT_PLAYBOOK.md). Backlog de mejoras priorizadas: [docs/IMPROVEMENT_BACKLOG.md](docs/IMPROVEMENT_BACKLOG.md).

---

## 1. Cómo navegar el código (graphify-first)

Hay un knowledge graph en `graphify-out/` con god nodes, comunidades y relaciones cross-file. Úsalo **antes** que grep cuando exista `graphify-out/graph.json`.

| Necesidad | Comando |
|---|---|
| Pregunta abierta sobre arquitectura | `graphify query "<pregunta>"` |
| Relación entre dos símbolos/módulos | `graphify path "<A>" "<B>"` |
| Entender un concepto/módulo concreto | `graphify explain "<concepto>"` |
| Navegación broad | `graphify-out/wiki/index.md` si existe, si no `GRAPH_REPORT.md` (146K, solo si los anteriores no bastan) |

Dirty graphify-out/ tras hooks o updates incrementales es **normal** — no es razón para saltarse graphify. Solo saltátelo si la tarea es sobre stale graph output o el usuario lo dice explícito.

Lee archivos raw solo cuando: (a) vas a modificar/depurar código concreto, (b) el graph no tiene el detalle necesario, (c) el graph está ausente o stale.

---

## 2. Mapa de áreas

| Paquete | Propósito | Entry point | Notas |
|---|---|---|---|
| `config/` | Settings, keywords, constants, secrets | `config/settings.py` | **typing strict** |
| `shared/` | Utilidades cross-cutting (auth_core, dto, geo, i18n, schemas, signing) | — | **typing strict** |
| `services/` | Lógica de dominio (licitaciones, classification, clusters, normalization, analytics) | `services/licitaciones.py` | Core; usa `db.repositories.*` |
| `db/` | Persistencia (SQLite/Turso), upsert idempotente, migraciones alembic | `db/database.py` (fachada → `connection/schema/upsert`) | `db.database`, `db.users` **strict** |
| `api/` | FastAPI REST | `api/app.py` (`uvicorn api.app:app`) | Rutas en `api/routes/` |
| `dashboard/` | Streamlit UI | `dashboard/app.py` | Typing **no strict** salvo `dashboard.bootstrap` |
| `scraper/` | Pipeline PLACSP (ZIPs + ATOM), parser CODICE/UBL, clasificador ML | `scraper/pipeline.py` | `ml_*` con SQL manual (S608 suppressed) |
| `scheduler/` | Jobs (run_update, kpi_precompute), loop | `scheduler/loop.py` | Cron de GitHub Actions |
| `llm/` | Cliente LLM y providers | `llm/client.py` | Opcional |
| `observability/` | structlog, Prometheus, healthcheck, Grafana dashboards | `observability/logging.py` | — |
| `tests/` | pytest con auto-marking por nombre | `tests/conftest.py` | Markers: unit/integration/e2e/property/load/slow |

Detalle completo (con docs relacionados por paquete) en [docs/AGENT_PLAYBOOK.md](docs/AGENT_PLAYBOOK.md).

---

## 3. Invariantes que nunca romper

1. **Typing strict en core**: `config/*`, `db.database`, `db.users`, `shared/*`, `dashboard.bootstrap` pasan mypy strict. Si tocás estos módulos, mantenelos strict — no añadas `# type: ignore` ni `Any` sin justificar.
2. **Upsert idempotente**: cualquier escritura desde scraper debe poder re-ejecutarse sin duplicar (ver `db/upsert.py`).
3. **Migraciones append-only**: nunca modificar migraciones alembic ya commiteadas. Siempre nueva revisión.
4. **Auto-marking de tests**: `tests/conftest.py` aplica markers (unit/integration/e2e/property/load) por nombre de archivo. **No marcar a mano** — renombrar el test si necesitás otro marker.
5. **DTOs Pydantic v2** son el contrato API↔dashboard (`shared/dto.py`). Cambios a campos requieren migración consciente.
6. **HMAC-signed CSRF + argon2/bcrypt** para auth (`shared/auth_core.py`). No reemplazar por algo más débil.
7. **Pre-commit obligatorio**: ruff + mypy + bandit + gitleaks + detect-secrets corren en cada commit. No bypassear con `--no-verify`.

---

## 4. Comandos canónicos

Fuente única: [Makefile](Makefile). Targets clave:

```bash
make test-unit        # rápido (unit, no slow) — usá esto durante desarrollo
make test             # full suite excepto integration_e2e y dashboard_smoke
make test-integration # tests con BD real
make lint             # ruff check
make typecheck        # mypy .
make api              # arranca FastAPI en :8080
make dashboard        # arranca Streamlit
make scrape-daily     # corre scraper en modo daily
make doctor           # verifica entorno (scripts/doctor.py)
```

Slash-commands de Claude Code (en `.claude/commands/`):
- `/check` — lint + typecheck + test-unit
- `/graph-refresh` — `graphify update .` + verifica mtime
- `/find-improvements` — escanea TODOs, gaps de typing, tests skipped
- `/area <nombre>` — graphify explain + lista files + tests del paquete

---

## 5. Workflow estándar

**Pre-flight (siempre):**
1. Si `graphify-out/graph.json` existe → `graphify query "<intent>"` antes que grep.
2. Lee [docs/AGENT_PLAYBOOK.md](docs/AGENT_PLAYBOOK.md) si vas a tocar un área que no conocés.
3. Revisa [docs/IMPROVEMENT_BACKLOG.md](docs/IMPROVEMENT_BACKLOG.md) si te pidieron "encuentra una mejora".

**Durante:**
- Respetá los invariantes (sección 3).
- Si tocás un módulo strict, mantenelo strict.

**Post-flight (siempre tras editar `.py`):**
1. Corre `/check` (o `make lint && make typecheck && make test-unit`).
2. Corre `graphify update .` (AST-only, gratis, sin API). Si hubo cambios estructurales (nuevos módulos, renames), considerá `graphify update . --force`.
3. Si el cambio rompe convenciones documentadas, abrí un ADR en `docs/adr/` antes de mergear.
4. Si el cambio resuelve (total o parcialmente) un ítem de [docs/IMPROVEMENT_BACKLOG.md](docs/IMPROVEMENT_BACKLOG.md), movélo a **Cerrados** (o anotá progreso parcial) en ese mismo momento. No dejarlo para después.

---

## 6. Cuándo pedir confirmación al humano

Estas acciones requieren **OK explícito** antes de ejecutar:

- Tocar `db/alembic/` (migraciones de schema).
- Modificar secrets, `.env*`, `.gitleaks.toml`, `.secrets.baseline`.
- Editar workflows `.github/workflows/` (CI/CD, scrape, release).
- Cambiar dependencias en `pyproject.toml`, `requirements*.in`, `requirements*.txt`.
- Borrar tests existentes o relajar markers strict en `pyproject.toml`.
- `git push`, `git reset --hard`, force-push, ramas borradas.
- Crear/cerrar PRs e issues en GitHub.

Para todo lo demás (editar código de feature, añadir tests, refactor local), procedé sin pedir confirmación a menos que el cambio sea irreversible.

---

## 7. Referencias

- Arquitectura C4: [docs/c4-architecture.md](docs/c4-architecture.md)
- Schema DB: [docs/database-schema.md](docs/database-schema.md)
- ADRs: [docs/adr/](docs/adr/)
- Runbooks (incident, DLQ, backup, disaster recovery): [docs/runbooks/](docs/runbooks/)
- SLI/SLO: [docs/sli-slo.md](docs/sli-slo.md)
- Security: [docs/SECURITY.md](docs/SECURITY.md)
