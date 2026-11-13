# CLAUDE.md

@AGENTS.md

[AGENTS.md](AGENTS.md), importado arriba, es la fuente única de instrucciones (navegación, mapa de áreas, invariantes, comandos, workflow). Este archivo solo añade overrides específicos de Claude Code.

## Overrides Claude Code

**Slash-commands** (`.claude/commands/`): `/check`, `/graph-refresh`, `/find-improvements`, `/area <nombre>`, `/cerrar`. Son la fuente canónica de esos cinco workflows; `.agents/skills/source-command-*/` son copias para otras herramientas y no deben divergir. `/cerrar` va después del merge: quita los worktrees y ramas locales ya integrados (`scripts/cerrar_ramas.py`, que cruza con los PR porque el squash los esconde de `git branch --merged`), previo OK del usuario.

**Subagente `revisor`** (`.claude/agents/revisor.md`): antes de abrir el PR de un cambio de código (`gh pr create`, o la herramienta MCP de GitHub en una sesión remota), lanzalo con el rango del diff y lo que pidió el usuario, sin tu razonamiento, para que su lectura no se ancle en la tuya. Busca lo que los ratchets no ven (capa equivocada según ADR-024, DTO que cambia de significado, escritura no idempotente, dato inventado, test que no prueba el caso). Sus hallazgos se verifican antes de aplicarlos; no sustituye a §4. Es de solo lectura por instrucción, no por permisos: su Bash no está acotado.

**Skills**: Claude Code carga `.claude/skills/` (`.agents/skills/` es para Codex/OpenCode; ambos árboles se instalan desde `skills-lock.json` y deben tener el mismo contenido — `make check-agent-docs` lo verifica). La excepción es un skill que su instalador compila distinto por herramienta, como `impeccable`: el lock lo declara con `harnessVariants`, un hash por árbol (`.claude`, `.agents`, `.github`, `.opencode`), y lo que se verifica es que cada árbol siga siendo el instalado. Su binario no se versiona (está en `.gitignore`): el lanzador lo descarga la primera vez y lo verifica contra su `.sha256`.

**Son obligatorios cuando la tarea encaja, no sugerencias** (AGENTS.md §0): se
cargan con la herramienta Skill antes de escribir la primera línea del cambio,
según la ruta que se edita:

| Ruta | Skill |
| --- | --- |
| cualquier `.py`, `.ts` o `.tsx` del repo | `ponytail` (argumento lite) |
| `web/src/**` | `impeccable` |
| `db/**/*.py` fuera de `db/alembic/` | `supabase-postgres-best-practices` |
| `db/alembic/**` | `sqlalchemy-alembic-expert-best-practices-code-review` |
| `api/**` | `fastapi-python` (sus handlers async no aplican: `db/` es síncrono) |
| `tests/**` | `python-testing-patterns` (sin SQLite ni markers manuales: AGENTS.md §3.4) |

- **Las filas se suman**: un `.py` de `db/repositories/` exige `ponytail` y `supabase-postgres-best-practices`. El hook `pretooluse_edit_skills.py` bloquea la edición si falta alguno (ver **Hooks**).
- **Código con Edit o Write**: el hook solo ve las herramientas de edición (Edit, Write, MultiEdit). Reescribir un `.py`, `.ts` o `.tsx` desde Bash (un heredoc, `sed -i`, un script) se salta el control de skills: no se hace con código del repo.
- **Cargarlo, no recordarlo**: seguir sus reglas a mano no sustituye cargarlo. Un cambio que encaja con un skill que no se cargó no está terminado, aunque los controles de §4 estén en verde.
- **`ponytail`** se invoca con el argumento lite (sin él arranca en full y queda así toda la sesión): la escalera de AGENTS.md §0 antes de escribir, y una línea final con lo que se dejó fuera (§0 dice qué no exime).
- **`impeccable`** lee `PRODUCT.md` y `DESIGN.md`. Su hook no es su revisión: la revisión visual (pantallas renderizadas, o la vista previa de Vercel del PR) es parte de todo cambio en `web/src/`. Si en `web/` chocan, `ponytail` decide el alcance (qué se construye) e `impeccable` y los skills de diseño deciden el acabado de lo que sí se construye: recortar accesibilidad, estados vacíos o de error no es «ser lazy», es dejar la pantalla a medias.
- **Sin ruta propia**, pero igual de obligatorios cuando la tarea encaja: `python-patterns`, `pandas-pro` y `scikit-learn`.
- **De referencia**: `sqlalchemy`, `pydantic` y `supabase` (`disable-model-invocation: true`): leelos con Read, no se invocan como skill. A `supabase` se le quitó la invocación automática porque manda cambiar el esquema con `execute_sql` o `supabase migration`, y aquí el esquema cambia solo por Alembic (AGENTS.md §3.3); lo mismo vale para el plugin de Supabase que tengas instalado fuera del repo.

**No existe un skill `graphify`.** Las reglas del knowledge graph están en AGENTS.md §1 y en `.agents/rules/graphify.md`; para regenerarlo usá `/graph-refresh`. Sin el CLI, `python scripts/code_map.py` (AGENTS.md §1, paso 2).

**Hooks** (`.claude/settings.json`; cómo funciona cada uno está en su docstring, en `.claude/hooks/`, que es el único árbol: `.codex/hooks.json` lanza estos mismos ficheros):
- **Bloquean (exit 2):** `pretooluse_bash_grep_hint.py` frena la primera búsqueda de texto de la sesión hasta una llamada a `graphify query`, `explain` o `path`, si hay grafo y el CLI arranca; si no, avisa una vez y remite a `scripts/code_map.py`. `pretooluse_edit_skills.py` frena la edición si falta algún skill que la tabla de **Skills** exige para esa ruta (solo en Claude Code: Codex no tiene herramienta `Skill`).
- **Avisan:** `pretooluse_bash_revision_visual.py`, ante `git commit` o `gh pr create` con cambios en `web/src/`, recuerda la revisión visual (no ve un PR abierto por MCP: lo cubre el commit que lo precede). `userprompt_verificar_mejoras.py` (UserPromptSubmit), cuando el mensaje pide mejoras o lo que queda, recuerda leer `make backlog-estado` y verificar en el código antes de proponer (AGENTS.md §0). `session_start_contexto.py` trae `origin/master` (el clon remoto lo tiene atrasado; si no puede, lo avisa) y dice qué le falta al checkout, si la sesión hereda `ENV=prod` o una `DATABASE_URL`, si graphify o WSL no sirven en esta máquina, y qué PR y ramas hay en curso.
- **Mantienen:** `pretooluse_edit_stale.py` marca el grafo como viejo al editar un `.py`, y `stop_graph_refresh.py` lo rehace en segundo plano al acabar el turno. `session_start_pg.py` provisiona Postgres en sesiones remotas. El hook de Impeccable (SessionStart, PostToolUse y Stop) revisa los ficheros de UI; se configura en `.impeccable/config.json`.

Todos se lanzan con `if command -v python …; then python …; else python3 …; fi`: con `python … || python3 …`, cualquier código distinto de 0 (también el `exit 2` de bloqueo) hace correr `python3`, que en Windows es el alias de la Microsoft Store y devuelve 49.

En un worktree, Claude Code lanza los hooks desde el checkout principal: un cambio en un hook no llega a esas sesiones hasta que el checkout principal lo trae.

**Sesiones remotas (Claude Code web / CI)**: el hook `SessionStart`
(`.claude/hooks/session_start_pg.py`) provisiona Postgres al arrancar la sesión
—cluster local, rol, base, `pg_trgm`/`vector`— y deja `TEST_DATABASE_URL` en
`.env`, de donde `tests/conftest.py` la lee. Con eso **la suite sí se ejecuta**:
`make test-unit` y `make check` son válidos en remoto. Las dependencias Python
del proyecto no vienen en la imagen. El entorno cloud «Tenderflow» las instala
con su setup script (se edita en los ajustes del entorno, no en el repo); si al
arrancar no hay `.venv`, el hook de contexto lo dice y se hace a mano: en un
`.venv` (el `pip` del sistema no
puede reemplazar paquetes que instaló Debian), `pip install -r
requirements-dev.txt` —trae también los paquetes de producción:
`requirements-dev.in` empieza con `-r requirements.in`— y `pip install -e ".[pliegos]"` (este último lo exigen los
tests de extracción de PDF). El Makefile llama a `ruff`, `mypy` y `pytest` por
su nombre: activá el `.venv` antes de `make`. Mientras se instalan, `make gates`
ya corre (solo biblioteca estándar). `make lock` compila `requirements-dev.txt`
con `--constraint=requirements.txt`: CI prueba las mismas versiones que corre
producción.

Si el entorno de la sesión exporta configuración de la app (`DATABASE_URL`,
`ENV=prod` y lo que venga con ellas: Redis, LLM, plano del scheduler), gana
sobre `.env`: la suite falla por ella y un script apuntaría a esa base. El hook
de contexto lo avisa al arrancar; lanzá tests y scripts con el entorno limpio:
`env -i PATH="$PATH" HOME="$HOME" ENV=dev make test-unit`.

El hook es best-effort: si no consigue Postgres lo dice en su mensaje de
arranque, y entonces vuelve a aplicar la regla de AGENTS.md §4 — se reportan
explícitamente los controles no ejecutados en vez de darlos por verdes. El CLI
`graphify` sigue sin estar disponible en remoto: ahí se navega con
`python scripts/code_map.py` (AGENTS.md §1).
