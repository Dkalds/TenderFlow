# AGENTS.md

Fuente canónica de instrucciones para todos los agentes (Claude Code, Copilot, OpenCode, Cursor, etc.). `CLAUDE.md` y `.github/copilot-instructions.md` referencian este archivo y solo añaden overrides específicos de su plataforma. **Si editás reglas, editá aquí.**

Guía completa de navegación, workflows y patrones: [docs/AGENT_PLAYBOOK.md](docs/AGENT_PLAYBOOK.md). Backlog de mejoras priorizadas: [docs/IMPROVEMENT_BACKLOG.md](docs/IMPROVEMENT_BACKLOG.md). Diagnóstico UX/UI del frontend y su roadmap por olas: [docs/UX_AUDIT.md](docs/UX_AUDIT.md).

---

## 0. Estado y prioridades

**No hay freeze activo** (el de 2026-07 se levantó el 2026-07-11). Features
nuevas están permitidas.

Prioridad de trabajo: el orden de
[docs/IMPROVEMENT_BACKLOG.md](docs/IMPROVEMENT_BACKLOG.md) (activación
multi-fuente y confianza en el dato antes que features de superficie). Los 67
RFCs de UX existentes se implementan directamente sin nuevo RFC (ver política de
RFCs, §5).

Ningún hecho medible (conteos de tests, coverage, tamaño de ratchets, jobs por
plano) se escribe a mano en este archivo: vive en
[docs/STATUS.md](docs/STATUS.md), generado por `make status` y verificado en CI.
Si necesitás una cifra, leela de ahí.

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
| Navegación broad | `graphify-out/wiki/index.md` si existe, si no `GRAPH_REPORT.md` (varios cientos de KB — último recurso, solo si los anteriores no bastan) |

Dirty graphify-out/ tras hooks o updates incrementales es **normal** — no es razón para saltarse graphify; usalo igual. Solo saltátelo si la tarea es específicamente sobre regenerar el graph stale o el usuario lo dice explícito.

El post-flight `graphify update .` solo aplica si `which graphify` resuelve; si no, omitilo (el hook ya deja `graphify-out/.graph_stale` para regenerar local).

Lee archivos raw solo cuando: (a) vas a modificar/depurar código concreto, (b) el graph no tiene el detalle necesario, (c) el graph está ausente.

---

## 2. Mapa de áreas

| Paquete | Propósito | Entry point | Notas |
|---|---|---|---|
| `config/` | Settings, keywords, constants, secrets | `config/settings.py` | **typing strict** |
| `shared/` | Utilidades cross-cutting (auth_core, dto, geo, i18n, schemas, signing, ssrf, csrf) | — | **typing strict** |
| `services/` | Lógica de dominio (licitaciones, classification, clusters, normalization, `analytics/`, `competitive/`, `investigador/`, `ml/`, `rag/`) | `services/licitaciones.py` | Biblioteca de dominio, **no** frontera obligatoria de persistencia (ADR-024) — ver invariante §3.10 |
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

1. **Typing strict en todo el código de producción**: `pyproject.toml` declara `strict = true` global y desde 2026-05-29 **todos** los paquetes de producción pasan. Los únicos overrides son `tests.*`/`scripts.*` (no requieren strict) y dependencias de terceros sin stubs. No hay "módulos pendientes": si tocás cualquier `.py` de producción, sale strict o no sale. No añadas `# type: ignore` ni `Any` sin un comentario inline que explique el motivo (e.g., `# type: ignore[assignment]  # third-party lib lacks stubs`), y nunca abras un override nuevo de módulo en `pyproject.toml` — eso es una regresión del invariante, no un atajo.
2. **Upsert idempotente**: cualquier escritura desde scraper debe poder re-ejecutarse sin duplicar (ver `db/upsert.py`).
3. **Migraciones append-only**: nunca modificar migraciones alembic ya commiteadas. Siempre nueva revisión.
4. **Auto-marking de tests**: `tests/conftest.py` aplica markers (unit/integration/e2e/property/load) por nombre de archivo. **No marcar a mano** — renombrar el test si necesitás otro marker.
5. **DTOs Pydantic v2** son el contrato API↔web (`shared/dto.py`). Cambios a campos requieren migración consciente. Una ruta nueva **nace tipada**: `dict[str, Any]` genera `{ [key: string]: unknown }` en el cliente y obliga al frontend a duplicar la forma a mano. `scripts/check_openapi_contract.py` es un ratchet con allowlist decreciente — **no se le añaden entradas**.
6. **HMAC-signed CSRF + argon2/bcrypt** para auth (`shared/auth_core.py`). No reemplazar por algo más débil.
7. **Pre-commit obligatorio**: ruff + mypy + bandit + codespell + gitleaks + detect-secrets + `check-agent-docs` corren en cada commit (`.pre-commit-config.yaml` es la lista vigente). No bypassear con `--no-verify`.
8. **Frontend siempre vía API**: `web/` no accede a `db.*` ni a la capa Python de servicios de forma directa; consume `api/` mediante HTTP/OpenAPI y contratos tipados. Código nuevo **debe** respetar este invariante.
9. **Un solo plano de orquestación por entorno**: los planos GitHub Actions y APScheduler nunca corren activos contra la misma BD (ADR-012). Variable `SCHEDULER_PLANE` declara el dueño.
10. **Todo el SQL vive en `db/`** (ADR-022). `db/repositories/*` (clases) y `db/*.py` (funciones de módulo) son **el mismo estrato** — la diferencia es estilística, no arquitectónica, y ninguno se migra al otro. Lo que sí es violación es SQL fuera de `db/`: `services/`, `api/`, `scheduler/`, `scraper/` y `scripts/` no escriben SQL. El ratchet TID251 (whitelist decreciente en `pyproject.toml`; el conteo vigente está en [docs/STATUS.md](docs/STATUS.md)) lo sostiene prohibiendo importar `db.connection.connect`/`connect_read` fuera de la whitelist. Los alias de la fachada (`db.database.connect`/`connect_read`) están baneados igual: la fachada no es una vía de escape para abrir conexiones. **La whitelist sólo puede encoger, nunca añadir archivos.** Excepción acotada: `services/sql_fragments.py` expone fragmentos SQL constantes pero no ejecuta nada.

    **Quién puede llamar a `db/`** (ADR-024): este invariante gobierna *dónde vive el SQL*, no *qué capa invoca persistencia*. `services/` es biblioteca de dominio, no frontera obligatoria. La regla vigente es **CRUD simple → `db.*` directo (incluido desde `api/routes/`); regla de negocio o transformación de dominio → `services/`**. No refactorices un passthrough (leer por id, listar paginado, log de auditoría, crear/revocar sesión) para meterle una capa de servicio que no transforma nada.

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
make check-api-contract         # ratchet del contrato API↔web (ninguna operación nueva opaca)
make check-agent-docs           # las instrucciones de agentes citan cosas que existen
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

**Qué se puede correr en un entorno incompleto** (sesión remota de Claude Code,
contenedor recién creado, CI de docs). Son dos prerequisitos distintos —
dependencias instaladas y Postgres levantado — y conviene no confundirlos:

| Comando | Sin deps instaladas | Con deps, sin Postgres |
|---|---|---|
| `make lint` (ruff) | ✅ | ✅ |
| `make check-agent-docs` (stdlib) | ✅ | ✅ |
| `make check-frontend-invariants` (stdlib) | ✅ | ✅ |
| `make typecheck` (mypy) | ❌ `import-not-found` en cascada | ✅ |
| `make status`, `make job-parity` | ❌ importa el paquete | ✅ |
| `make check-api-contract` | ❌ | ✅ tras `make openapi` |
| `make test-unit`, `make test`, `make check` | ❌ | ❌ `pytest.UsageError`: falta `TEST_DATABASE_URL` |
| `graphify *` | solo si `which graphify` resuelve (§1) | idem |

Lo que no pudiste correr **se reporta explícitamente**: "lint y check-agent-docs
verdes; typecheck y tests no ejecutados (sin deps/Postgres en este entorno)". No
cuenta como verde, y no se sustituye por `pytest` con otro motor ni por leer el
código "con atención".

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
1. Corre `/check` (o `make lint && make typecheck && make test-unit`). Si el entorno no tiene Postgres, corré lint+typecheck y reportá los tests como no ejecutados (§4) — nunca declares verde lo que no corriste.
2. Si el CLI está disponible (`which graphify`), corre `graphify update .` (AST-only, gratis, sin API). Si hubo cambios estructurales (nuevos módulos, renames), considerá `graphify update . --force`. Si el CLI no está (CI/remoto), omití este paso.
3. Si el cambio contradice una decisión registrada en `docs/adr/` o un invariante de la sección 3, abrí una nueva revisión ADR en `docs/adr/` antes de mergear.
4. Si el cambio resuelve (total o parcialmente) un ítem de [docs/IMPROVEMENT_BACKLOG.md](docs/IMPROVEMENT_BACKLOG.md), movélo a **Cerrados** (o anotá progreso parcial) en ese mismo momento. No dejarlo para después.
5. Si tocaste instrucciones de agentes (`AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`, `docs/AGENT_PLAYBOOK.md`, `.claude/`, `.agents/`, `.codex/`, `.opencode/`), corré `make check-agent-docs`: valida que los comandos `make`, slash-commands, skills, hooks y rutas que citan existan de verdad.

**Regla general de las instrucciones:** describen el estado real del repo, no la intención. Si encontrás una que el código desmiente, arreglá la instrucción en el mismo cambio (o anotala en el backlog si el arreglo es grande) — una instrucción falsa cuesta más que ninguna.

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
- `git reset --hard`, force-push, ramas borradas, reescritura de historia.
- `git push`, **excepto** cuando el usuario o el harness ya asignaron una rama de trabajo para la tarea (típico en Claude Code web / sesiones remotas): a esa rama se pushea sin volver a preguntar. A `master` nunca se pushea directo.
- Crear/cerrar PRs e issues en GitHub (incluso desde una rama ya autorizada).

Si durante la ejecución de una tarea descubrís que completarla requiere una acción de esta lista, detené la tarea, describí qué acción necesitás y por qué, y esperá confirmación explícita antes de continuar.

Para todo lo demás (editar código de feature, añadir tests, refactor local), procedé sin pedir confirmación a menos que el cambio sea irreversible.

---

## 7. Referencias

**Decisiones que más citan estos invariantes:** ADR-012 (plano único de
orquestación), ADR-021 (retirada de SQLite), ADR-022 (frontera de persistencia),
ADR-023 (cómputo en vivo / agregación SQL), ADR-024 (`services/` es biblioteca,
no frontera).

**Dónde viven las instrucciones de agentes** (este archivo es la fuente; el
resto solo añade overrides de plataforma y **no** duplica reglas):

| Archivo | Para | Contenido propio |
|---|---|---|
| `AGENTS.md` | todos | reglas del proyecto (este archivo) |
| `CLAUDE.md` | Claude Code | slash-commands, skills, hooks |
| `.github/copilot-instructions.md` | Copilot | equivalencias sin `.claude/commands/` |
| `docs/AGENT_PLAYBOOK.md` | todos | detalle accionable: paquetes, workflows, glosario |
| `.agents/rules/graphify.md` | Codex/OpenCode/Cursor | regla graphify always-on |
| `.claude/commands/*.md` | Claude Code | los 4 workflows canónicos |
| `.claude/skills/`, `.agents/skills/` | Claude Code / resto | skills instalados vía `skills-lock.json` |
| `.claude/settings.json`, `.codex/hooks.json`, `.opencode/opencode.json` | cada herramienta | hooks/plugins |

`make check-agent-docs` verifica que lo que estos archivos citan (targets,
comandos, skills, hooks, rutas) exista.

- Arquitectura C4: [docs/c4-architecture.md](docs/c4-architecture.md)
- Schema DB: [docs/database-schema.md](docs/database-schema.md)
- Diseño de la API REST: [docs/api-design.md](docs/api-design.md)
- ADRs: [docs/adr/](docs/adr/)
- Runbooks (incident, DLQ, backup, disaster recovery): [docs/runbooks/](docs/runbooks/)
- SLI/SLO: [docs/sli-slo.md](docs/sli-slo.md)
- Security: [docs/SECURITY.md](docs/SECURITY.md)
