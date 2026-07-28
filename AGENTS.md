# AGENTS.md

Fuente canónica de instrucciones para todos los agentes (Claude Code, Copilot, OpenCode, Cursor, etc.). `CLAUDE.md` y `.github/copilot-instructions.md` referencian este archivo y solo añaden overrides específicos de su plataforma. **Si editás reglas, editá aquí.**

Guía completa de navegación, workflows y patrones: [docs/AGENT_PLAYBOOK.md](docs/AGENT_PLAYBOOK.md). Backlog de mejoras priorizadas: [docs/IMPROVEMENT_BACKLOG.md](docs/IMPROVEMENT_BACKLOG.md).

---

## 0. FREEZE de features — LEVANTADO (2026-07-11)

El freeze de 2026-07 se levantó el **2026-07-11**: sus condiciones se cumplieron
(F2 Retrofit PLACSP y F4a/b Dev/prod parity merged el 2026-07-05; `make check`
verde — ruff limpio, mypy 461 archivos, 2290 unit tests, coverage 78.2%).

Features nuevas vuelven a estar permitidas. Prioridad de trabajo: seguir el
orden de [docs/IMPROVEMENT_BACKLOG.md](docs/IMPROVEMENT_BACKLOG.md) (activación
multi-fuente y confianza en el dato antes que features de superficie). Los 67
RFCs de UX existentes se implementan directamente sin nuevo RFC (ver política
de RFCs, §5).

---

## 1. Cómo navegar el código (graphify-first)

Hay un knowledge graph en `graphify-out/` con god nodes, comunidades y relaciones cross-file. Úsalo **antes** que grep para entender arquitectura y relaciones cross-file.

**Orden de navegación (prioridad):**
1. Si `which graphify` resuelve → usá el CLI (tabla de comandos abajo). `graphify` es una herramienta local del mantenedor — **no está en PyPI ni npm, no intentes instalarla**.
2. Si no, pero `graphify-out/graph.json` existe → leé los artefactos commiteados directamente (`graphify-out/graph.json`, `graphify-out/wiki/` o `GRAPH_REPORT.md`) en vez de invocar el CLI. Típico en CI o sesiones remotas de Claude Code.
3. Si no → navegá con grep + [docs/AGENT_PLAYBOOK.md](docs/AGENT_PLAYBOOK.md) y el mapa de áreas de abajo. No es un error: seguí con la tarea.

| Necesidad | Comando |
|---|---|
| Pregunta abierta sobre arquitectura | `graphify query "<pregunta>"` |
| Relación entre dos símbolos/módulos | `graphify path "<A>" "<B>"` |
| Entender un concepto/módulo concreto | `graphify explain "<concepto>"` |
| Navegación broad | `graphify-out/wiki/index.md` si existe, si no `GRAPH_REPORT.md` (146K, solo si los anteriores no bastan) |

Dirty graphify-out/ tras hooks o updates incrementales es **normal** — no es razón para saltarse graphify; usalo igual. Solo saltátelo si la tarea es específicamente sobre regenerar el graph stale o el usuario lo dice explícito.

El post-flight `graphify update .` solo aplica si `which graphify` resuelve; si no, omitilo (el hook ya deja `graphify-out/.graph_stale` para regenerar local).

Lee archivos raw solo cuando: (a) vas a modificar/depurar código concreto, (b) el graph no tiene el detalle necesario, (c) el graph está ausente.

---

## 2. Mapa de áreas

| Paquete | Propósito | Entry point | Notas |
|---|---|---|---|
| `config/` | Settings, keywords, constants, secrets | `config/settings.py` | **typing strict** |
| `shared/` | Utilidades cross-cutting (auth_core, dto, geo, i18n, schemas, signing, ssrf, csrf) | — | **typing strict** |
| `services/` | Lógica de dominio (licitaciones, classification, clusters, normalization, `analytics/`, `competitive/`, `investigador/`, `ml/`, `rag/`) | `services/licitaciones.py` | Core; usa `db.repositories.*` |
| `db/` | Persistencia — **Postgres es el único motor** (ADR-016 producción, ADR-021 dev/CI; psycopg3. Turso retirado ADR-020, SQLite ADR-021). Upsert batcheado e idempotente, migraciones solo Alembic | `db/database.py` (fachada → `connection/schema/upsert/search_backend`) | `db.database`, `db.users` **strict** |
| `api/` | FastAPI REST | `api/app.py` (`uvicorn api.app:app`) | Rutas en `api/routes/` (incl. `ask.py` RAG, `analytics.py`, `competitive.py`) |
| `web/` | Frontend Next.js 16 | `web/` | Consume la API tipada generada desde OpenAPI |
| `scraper/` | Pipeline multi-fuente (`connectors/`: PLACSP, PSCP, TACRC, TED — ADR-009), parser CODICE/UBL, clasificador ML | `scraper/pipeline.py` | `ml_*` con SQL manual (S608 suppressed) |
| `scheduler/` | Jobs (run_update, kpi_precompute, aggregates_precompute, drift, alertas), loop | `scheduler/loop.py` | Cron de GitHub Actions |
| `llm/` | Cliente LLM, presupuesto/circuit-breaker (`budget.py`) y providers (NVIDIA NIM/OpenAI/Anthropic) | `llm/client.py` | Opcional; usado por `api/routes/ask.py` |
| `observability/` | structlog, Prometheus, healthcheck, Grafana dashboards | `observability/logging.py` | — |
| `tests/` | pytest con auto-marking por nombre | `tests/conftest.py` | Markers: unit/integration/e2e/property/load/slow |

Detalle completo (con docs relacionados por paquete) en [docs/AGENT_PLAYBOOK.md](docs/AGENT_PLAYBOOK.md).

---

## 3. Invariantes que nunca romper

1. **Typing strict en core**: `db.database` y `db.users` pasan mypy strict. `config/*` y `shared/*` están en proceso de migración a strict (ver bloque de overrides en `pyproject.toml`). Si tocás estos módulos, **no empeores** el estado de typing — no añadas `# type: ignore` ni `Any` sin un comentario inline que explique el motivo (e.g., `# type: ignore[assignment]  # third-party lib lacks stubs`), y priorizá cerrar overrides existentes sobre abrir nuevos.
2. **Upsert idempotente**: cualquier escritura desde scraper debe poder re-ejecutarse sin duplicar (ver `db/upsert.py`).
3. **Migraciones append-only**: nunca modificar migraciones alembic ya commiteadas. Siempre nueva revisión.
4. **Auto-marking de tests**: `tests/conftest.py` aplica markers (unit/integration/e2e/property/load) por nombre de archivo. **No marcar a mano** — renombrar el test si necesitás otro marker.
5. **DTOs Pydantic v2** son el contrato API↔web (`shared/dto.py`). Cambios a campos requieren migración consciente.
6. **HMAC-signed CSRF + argon2/bcrypt** para auth (`shared/auth_core.py`). No reemplazar por algo más débil.
7. **Pre-commit obligatorio**: ruff + mypy + bandit + gitleaks + detect-secrets corren en cada commit. No bypassear con `--no-verify`.
8. **Frontend siempre vía API**: `web/` no accede a `db.*` ni a la capa Python de servicios de forma directa; consume `api/` mediante HTTP/OpenAPI y contratos tipados. Código nuevo **debe** respetar este invariante.
9. **Un solo plano de orquestación por entorno**: los planos GitHub Actions y APScheduler nunca corren activos contra la misma BD (ADR-012). Variable `SCHEDULER_PLANE` declara el dueño.
10. **Acceso a BD solo vía `db/repositories/*`** (TID251, whitelist decreciente): el acceso directo a `db.connection.connect` / `db.connection.connect_read` / `db.database.connect` / `db.database.connect_read` está baneado por ruff fuera de la whitelist declarada en `pyproject.toml`. La whitelist se congela en el estado actual y **solo se puede encoger** — nunca añadir archivos nuevos.

---

## 4. Comandos canónicos

Fuente única: [Makefile](Makefile). Targets clave:

```bash
make check            # lint + typecheck + test-unit (equivale a /check)
make test-unit        # rápido (unit, no slow) — usá esto durante desarrollo
make test             # full suite excepto integration_e2e
make test-integration # tests con BD real
make lint             # ruff check
make typecheck        # mypy .
make api              # arranca FastAPI en :8080
make web-dev          # arranca Next.js en :3000
make web-lint         # ESLint del frontend
make web-typecheck    # tsc --noEmit del frontend
make web-test-e2e     # Playwright
make scrape-daily     # corre scraper en modo daily
make migrate-alembic  # aplica migraciones Alembic pendientes (sistema canónico)
make seed             # datos de ejemplo en BD local
make doctor           # verifica entorno (scripts/doctor.py)
make check-frontend-invariants  # integridad analítica del frontend (ADR-014, bloqueante)
make status           # regenera docs/STATUS.md desde el código
make job-parity       # verifica que todo job tiene plano de ejecución (ADR-012)
```

**Estado derivado del código:** [docs/STATUS.md](docs/STATUS.md) se genera con
`make status` y CI verifica que esté sincronizado. Contiene la paridad de jobs
por plano, el conteo del ratchet TID251, el motor de la suite y la superficie de
la API. **No lo edites a mano** — si un hecho se puede calcular, se calcula.

**Motor de tests:** Postgres, siempre (ADR-021). `TEST_DATABASE_URL` es
**obligatoria** — la suite falla al arrancar sin ella. Levantá el Postgres de
dev con `docker compose up -d postgres`. Cada test recibe un schema aislado
sobre esa instancia (`tests/conftest.py::_pg_schema`).

Slash-commands de Claude Code (en `.claude/commands/`):
- `/check` — lint + typecheck + test-unit
- `/graph-refresh` — `graphify update .` + verifica mtime
- `/find-improvements` — escanea TODOs, gaps de typing, tests skipped
- `/area <nombre>` — graphify explain + lista files + tests del paquete

---

## 5. Workflow estándar

**Pre-flight (siempre):**
1. Si `graphify-out/graph.json` existe → `graphify query "<intent>"` antes que grep (ver lógica de fallback en §1).
2. Lee [docs/AGENT_PLAYBOOK.md](docs/AGENT_PLAYBOOK.md) si vas a tocar un área que no conocés.
3. Revisa [docs/IMPROVEMENT_BACKLOG.md](docs/IMPROVEMENT_BACKLOG.md) si te pidieron "encuentra una mejora".

**Durante:**
- Respetá los invariantes (sección 3).
- Si tocás un módulo strict, mantenelo strict.

**Post-flight (siempre tras editar `.py`):**
1. Corre `/check` (o `make lint && make typecheck && make test-unit`).
2. Si el CLI está disponible (`which graphify`), corre `graphify update .` (AST-only, gratis, sin API). Si hubo cambios estructurales (nuevos módulos, renames), considerá `graphify update . --force`. Si el CLI no está (CI/remoto), omití este paso.
3. Si el cambio contradice una decisión registrada en `docs/adr/` o un invariante de la sección 3, abrí una nueva revisión ADR en `docs/adr/` antes de mergear.
4. Si el cambio resuelve (total o parcialmente) un ítem de [docs/IMPROVEMENT_BACKLOG.md](docs/IMPROVEMENT_BACKLOG.md), movélo a **Cerrados** (o anotá progreso parcial) en ese mismo momento. No dejarlo para después.

### Política de RFCs (reducida desde 2026-07)

Un RFC formal (`docs/rfc/`) se requiere **solo** para:
- Cambios de schema/persistencia irreversibles (ej. migración de motor de BD).
- Cambios breaking al contrato API público (campos eliminados, semantica cambiada).
- Decisiones de seguridad/auth (nuevos mecanismos, rotación de secretos masiva).
- Borrado irreversible de datos de producción.

Para todo lo demás: backlog en [docs/IMPROVEMENT_BACKLOG.md](docs/IMPROVEMENT_BACKLOG.md) + PR directo. Los 67 RFCs de UX/features existentes **no generan nuevos RFCs** — se implementan directamente cuando el freeze lo permita.

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

Si durante la ejecución de una tarea descubrís que completarla requiere una acción de esta lista, detené la tarea, describí qué acción necesitás y por qué, y esperá confirmación explícita antes de continuar.

Para todo lo demás (editar código de feature, añadir tests, refactor local), procedé sin pedir confirmación a menos que el cambio sea irreversible.

---

## 7. Referencias

- Arquitectura C4: [docs/c4-architecture.md](docs/c4-architecture.md)
- Schema DB: [docs/database-schema.md](docs/database-schema.md)
- Diseño de la API REST: [docs/api-design.md](docs/api-design.md)
- ADRs: [docs/adr/](docs/adr/)
- Runbooks (incident, DLQ, backup, disaster recovery): [docs/runbooks/](docs/runbooks/)
- SLI/SLO: [docs/sli-slo.md](docs/sli-slo.md)
- Security: [docs/SECURITY.md](docs/SECURITY.md)
