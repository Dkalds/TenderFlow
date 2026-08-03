# AGENTS.md

Fuente canónica de instrucciones para todos los agentes. `CLAUDE.md` y
`.github/copilot-instructions.md` solo añaden adaptaciones de plataforma. **Si
editás una regla común, editála aquí.**

Este archivo contiene únicamente reglas siempre relevantes. El detalle
operativo vive en [docs/AGENT_PLAYBOOK.md](docs/AGENT_PLAYBOOK.md), el estado
calculado en [docs/STATUS.md](docs/STATUS.md), el trabajo priorizado en
[docs/IMPROVEMENT_BACKLOG.md](docs/IMPROVEMENT_BACKLOG.md) y el diagnóstico
UX/UI del frontend con su roadmap por olas en
[docs/UX_AUDIT.md](docs/UX_AUDIT.md).

---

## 0. Alcance y prioridades

Las features nuevas están permitidas. Salvo que el usuario priorice otra cosa,
seguí el orden de [docs/IMPROVEMENT_BACKLOG.md](docs/IMPROVEMENT_BACKLOG.md).

No escribas aquí hechos calculables (conteos de tests, coverage, tamaño de
ratchets, jobs o endpoints): pertenecen a [docs/STATUS.md](docs/STATUS.md), que
genera `make status`. Los RFCs de features ya existentes se implementan sin
crear otro RFC; las excepciones están en la política de §5.

---

## 1. Cómo navegar el código (graphify-first)

Usá este orden para preguntas de arquitectura y relaciones cross-file:

1. Si el ejecutable `graphify` está disponible, usá `graphify query`,
    `graphify path` o `graphify explain`. Es una herramienta local del mantenedor:
    **no está en PyPI ni npm y no debe instalarse**.
2. Si el CLI no está pero existe `graphify-out/graph.json`, consultá los
    artefactos commiteados en `graphify-out/` (`wiki/`, `graph.json` y, como
    último recurso, `GRAPH_REPORT.md`).
3. Si tampoco hay artefactos, usá búsqueda textual y el mapa de
    [docs/AGENT_PLAYBOOK.md](docs/AGENT_PLAYBOOK.md). Seguí con la tarea: la
    ausencia del CLI no es un error.

Que `graphify-out/` esté dirty tras hooks o actualizaciones incrementales es
normal. Leé archivos raw cuando vayas a modificar o depurar código concreto, o
cuando el grafo no tenga el detalle necesario.

---

## 2. Mapa de áreas

El mapa detallado, entry points y documentación por paquete viven en
[docs/AGENT_PLAYBOOK.md](docs/AGENT_PLAYBOOK.md). Límites que hay que conservar:

- `db/` posee la persistencia y todo SQL.
- `services/` contiene reglas y transformaciones de dominio; no es una frontera
    obligatoria para CRUD simple.
- `api/` expone HTTP y `web/` solo consume contratos tipados de esa API.
- `scraper/` ingiere y clasifica; `scheduler/` orquesta su ejecución.

---

## 3. Invariantes que nunca romper

1. **Typing strict en todo el código de producción**: `pyproject.toml` declara `strict = true` global. Los únicos overrides son `tests.*`/`scripts.*` y dependencias de terceros sin stubs. Si tocás cualquier `.py` de producción, sale strict o no sale. No añadas `# type: ignore` ni `Any` sin un comentario inline que explique el motivo, y nunca abras un override nuevo de módulo en `pyproject.toml`.
2. **Upsert idempotente**: cualquier escritura desde scraper debe poder re-ejecutarse sin duplicar (ver `db/upsert.py`).
3. **Migraciones append-only**: nunca modificar migraciones alembic ya commiteadas. Siempre nueva revisión.
4. **Auto-marking de tests**: `tests/conftest.py` infiere `unit`, `integration`, `e2e`, `property` y `load` por nombre, y además marca `integration` todo test cuyo cierre de fixtures abra Postgres (`tmp_db`/`api_db`, directo o transitivo vía `client`/`api_key`/`auth`) — `unit` significa "sin BD" de verdad. No introduzcas markers manuales de categoría: renombrá el test (la categoría por BD sale sola del fixture). Las excepciones históricas están congeladas por `scripts/check_agent_docs.py`; `slow` sí puede marcarse explícitamente. `make check` corre `unit or integration`; `make test-unit` es el bucle rápido sin BD.
5. **DTOs Pydantic v2** son el contrato API↔web (`shared/dto.py`). Cambios a campos requieren migración consciente. Una ruta nueva **nace tipada**: `dict[str, Any]` genera `{ [key: string]: unknown }` en el cliente y obliga al frontend a duplicar la forma a mano. `scripts/check_openapi_contract.py` es un ratchet con allowlist decreciente — **no se le añaden entradas**.
6. **HMAC-signed CSRF + argon2/bcrypt** para auth (`shared/auth_core.py`). No reemplazar por algo más débil.
7. **Pre-commit obligatorio**: ruff + mypy + bandit + codespell + gitleaks + detect-secrets + `check-agent-docs` corren en cada commit (`.pre-commit-config.yaml` es la lista vigente). No bypassear con `--no-verify`.
8. **Frontend siempre vía API**: `web/` no accede a `db.*` ni a la capa Python de servicios de forma directa; consume `api/` mediante HTTP/OpenAPI y contratos tipados. Código nuevo **debe** respetar este invariante.
9. **Un solo plano de orquestación por entorno**: los planos GitHub Actions y APScheduler nunca corren activos contra la misma BD (ADR-012). Variable `SCHEDULER_PLANE` declara el dueño.
10. **Todo el SQL vive en `db/`** (ADR-022). `db/repositories/*` (clases) y `db/*.py` (funciones de módulo) son el mismo estrato; ninguno se migra al otro por estilo. SQL nuevo fuera de `db/` está prohibido. El ratchet TID251 mantiene congeladas las violaciones legacy en `services/`, `api/`, `scheduler/`, `scraper/` y `scripts/`: su whitelist solo puede encoger. También prohíbe abrir `db.connection.connect`/`connect_read` o sus alias en `db.database` fuera de esa whitelist. Excepción acotada: `services/sql_fragments.py` expone fragmentos constantes pero no los ejecuta. El conteo vigente está en [docs/STATUS.md](docs/STATUS.md).

    **Quién puede llamar a `db/`** (ADR-024): este invariante gobierna *dónde vive el SQL*, no *qué capa invoca persistencia*. `services/` es biblioteca de dominio, no frontera obligatoria. La regla vigente es **CRUD simple → `db.*` directo (incluido desde `api/routes/`); regla de negocio o transformación de dominio → `services/`**. No refactorices un passthrough (leer por id, listar paginado, log de auditoría, crear/revocar sesión) para meterle una capa de servicio que no transforma nada.

---

## 4. Validación y comandos

El [Makefile](Makefile) es la fuente de comandos; el catálogo y la matriz de
prerrequisitos están en [docs/AGENT_PLAYBOOK.md](docs/AGENT_PLAYBOOK.md).

- Para cambios Python: `make lint`, `make typecheck` y `make test-unit`.
    `make check` es el atajo fail-fast que ejecuta esos tres en orden.
- `/check` es un workflow de Claude que ejecuta los mismos controles de forma
    independiente para reportar todos los resultados; no es un alias de shell de
    `make check`.
- Para cambios frontend: `make web-lint`, `make web-typecheck` y los tests
    relevantes. Los cambios analíticos también requieren
    `make check-frontend-invariants`.
- Para contratos API: `make check-api-contract`. Para customizaciones de
    agentes: `make check-agent-docs`.
- Gates que exigen BD sembrada y por eso no entran en `make check`: `make
    fuzz-api` (ninguna operación puede devolver 5xx; ratchet `KNOWN_5XX` que
    solo encoge) y los E2E de Playwright, que en CI corren contra Postgres +
    API + build de producción y **bloquean el merge**. `make audit-truth-check`
    mide la verdad del dato contra una BD real y su versión programada avisa
    por email. `make mutation-sample` es informe periódico, no gate.

Los tests usan exclusivamente Postgres y requieren `TEST_DATABASE_URL`. Si
faltan dependencias, Postgres o el CLI de Graphify, ejecutá solo los controles
disponibles y reportá explícitamente cuáles no se ejecutaron y por qué. Un
control omitido no cuenta como verde y no se sustituye por otro motor.

[docs/STATUS.md](docs/STATUS.md) se regenera con `make status`; no lo edites a
mano.

---

## 5. Workflow estándar

**Pre-flight (siempre):**
1. Seguí el orden Graphify CLI → artefactos commiteados → búsqueda textual de §1.
2. Lee [docs/AGENT_PLAYBOOK.md](docs/AGENT_PLAYBOOK.md) si vas a tocar un área que no conocés.
3. Revisa [docs/IMPROVEMENT_BACKLOG.md](docs/IMPROVEMENT_BACKLOG.md) si te pidieron "encuentra una mejora".

**Durante:**
- Respetá los invariantes (sección 3).
- Todo módulo Python de producción debe seguir pasando strict.

**Post-flight (siempre tras editar `.py`):**
1. Corré `/check` o los tres controles Python de §4. Si faltan prerrequisitos, reportá los controles no ejecutados.
2. Si el CLI está disponible, corré `graphify update .`; usá `--force` para módulos nuevos, renames o moves. Si no está, omitilo.
3. Si el cambio contradice una decisión registrada en `docs/adr/` o un invariante de la sección 3, abrí una nueva revisión ADR en `docs/adr/` antes de mergear.
4. Si el cambio resuelve (total o parcialmente) un ítem de [docs/IMPROVEMENT_BACKLOG.md](docs/IMPROVEMENT_BACKLOG.md), movélo a **Cerrados** (o anotá progreso parcial) en ese mismo momento. No dejarlo para después.
5. Si tocaste customizaciones de agentes, corré `make check-agent-docs`.

**Regla general de las instrucciones:** describen el estado real del repo, no la intención. Si encontrás una que el código desmiente, arreglá la instrucción en el mismo cambio (o anotala en el backlog si el arreglo es grande) — una instrucción falsa cuesta más que ninguna.

### Política de RFCs

Un RFC formal (`docs/rfc/`) se requiere **solo** para:
- Cambios de schema/persistencia irreversibles (ej. migración de motor de BD).
- Cambios breaking al contrato API público (campos eliminados, semantica cambiada).
- Decisiones de seguridad/auth (nuevos mecanismos, rotación de secretos masiva).
- Borrado irreversible de datos de producción.

Para todo lo demás: backlog en [docs/IMPROVEMENT_BACKLOG.md](docs/IMPROVEMENT_BACKLOG.md) + PR directo. Los RFCs de UX/features existentes no generan nuevos RFCs.

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
- Ejecutar la capacidad real de un skill con efectos externos (deploy,
    automatización de navegador contra un sitio real, CLI de infraestructura
    contra recursos reales — ej. `deploy-to-vercel`, `agent-browser`,
    `upstash-cli`) sin que el usuario haya pedido esa acción puntual. Esto
    aplica sin importar el `trust` del skill: `trust: first-party` clasifica
    la confianza en el *origen* (el vendor que lo publica), no si la *acción*
    en sí es segura de ejecutar sin permiso. El skill puede estar instalado y
    usarse para consulta/lectura de su documentación libremente; lo que
    requiere OK explícito es invocar la acción que cambia estado fuera del
    repo.

Si durante la ejecución de una tarea descubrís que completarla requiere una acción de esta lista, detené la tarea, describí qué acción necesitás y por qué, y esperá confirmación explícita antes de continuar.

Para todo lo demás (editar código de feature, añadir tests, refactor local), procedé sin pedir confirmación a menos que el cambio sea irreversible.

---

## 7. Referencias

- [docs/AGENT_PLAYBOOK.md](docs/AGENT_PLAYBOOK.md): paquetes, workflows,
  comandos, prerrequisitos y glosario.
- [docs/c4-architecture.md](docs/c4-architecture.md),
  [docs/database-schema.md](docs/database-schema.md) y
  [docs/api-design.md](docs/api-design.md): arquitectura y contratos.
- [docs/adr/](docs/adr/), [docs/runbooks/](docs/runbooks/),
  [docs/sli-slo.md](docs/sli-slo.md) y [docs/SECURITY.md](docs/SECURITY.md):
  decisiones y operación.

`AGENTS.md` es la fuente común; `CLAUDE.md` y
`.github/copilot-instructions.md` solo adaptan plataformas. Los commands viven
en `.claude/commands/`, sus copias portables en `.agents/skills/source-command-*`
y los skills instalados en `skills-lock.json`.

`make check-agent-docs` valida targets y rutas citadas, slash-commands, paridad
recursiva de skills, copias exactas de commands, equivalencia de hooks y plugins
OpenCode.

Cada skill de `skills-lock.json` declara `trust` (`first-party`: org del vendor
de la herramienta que documenta — `anthropics`, `vercel-labs`, `upstash`,
`supabase`; `community`: cualquier otro mantenedor). Ver
`scripts/classify_skill_trust.py`. Tabla completa (nombre, trust, source,
descripción) en [docs/skills-inventory.md](docs/skills-inventory.md),
generada con `make skills-inventory` (`scripts/gen_skills_inventory.py`) — no
se edita a mano.

**Asimetría de enforcement entre clientes**: solo `.claude/settings.json`
declara un `permissions.allow` (allow-list de comandos Bash auto-aprobados).
`.codex/hooks.json` y `.opencode/opencode.json` no tienen un mecanismo
equivalente en este repo — Codex y OpenCode no auto-aprueban ni restringen
comandos a nivel de repo, así que la sección 6 de este archivo (y no la config
de Claude) es la única barrera real para esos dos clientes. No asumas que
restringir `.claude/settings.json` alcanza para todos los clientes.
