# CLAUDE.md

@AGENTS.md

[AGENTS.md](AGENTS.md), importado arriba, es la fuente única de instrucciones (navegación, mapa de áreas, invariantes, comandos, workflow). Este archivo solo añade overrides específicos de Claude Code.

## Overrides Claude Code

**Slash-commands** (`.claude/commands/`): `/check`, `/graph-refresh`, `/find-improvements`, `/area <nombre>`. Son la fuente canónica de esos cuatro workflows; `.agents/skills/source-command-*/` son copias para otras herramientas y no deben divergir.

**Skills**: Claude Code carga `.claude/skills/` (`.agents/skills/` es para Codex/OpenCode; ambos árboles se instalan desde `skills-lock.json` y deben tener el mismo contenido — `make check-agent-docs` lo verifica). La excepción es un skill que su instalador compila distinto por herramienta, como `impeccable`: el lock lo declara con `harnessVariants`, un hash por árbol (`.claude`, `.agents`, `.github`, `.opencode`), y lo que se verifica es que cada árbol siga siendo el instalado. Su binario no se versiona (está en `.gitignore`): el lanzador lo descarga la primera vez y lo verifica contra su `.sha256`. Relevantes para este repo: `fastapi-python`, `python-patterns`, `python-testing-patterns`, `pandas-pro`, `scikit-learn`, `supabase-postgres-best-practices`, `sqlalchemy-alembic-expert-best-practices-code-review`, `impeccable` para trabajo de interfaz en `web/` (lee `PRODUCT.md` y `DESIGN.md`), y `ponytail` en nivel lite para cualquier cambio de código: la escalera de AGENTS.md §0 antes de escribir, y una línea final con lo que se dejó fuera (§0 dice qué no exime). **Son obligatorios cuando la tarea encaja, no
sugerencias**: se cargan con la herramienta Skill antes de escribir la primera
línea del cambio, según la ruta que se edita:

| Ruta | Skill |
| --- | --- |
| cualquier `.py`, `.ts` o `.tsx` del repo | `ponytail` |
| `web/src/**` | `impeccable` |
| `db/**/*.py` fuera de `db/alembic/` | `supabase-postgres-best-practices` |
| `db/alembic/**` | `sqlalchemy-alembic-expert-best-practices-code-review` |
| `api/**` | `fastapi-python` |
| `tests/**` | `python-testing-patterns` |

Las filas se suman: un `.py` de `db/repositories/` exige `ponytail` y
`supabase-postgres-best-practices`. El hook `pretooluse_edit_skills.py` bloquea
la edición si falta alguno (ver **Hooks**). Seguir sus reglas a mano no
sustituye cargarlo, y el hook de Impeccable no es su revisión: la revisión
visual (pantallas renderizadas, o la vista previa de Vercel del PR) es parte
de todo cambio en `web/src/`. Un cambio que encaja con un skill que no se cargó
no está terminado, aunque los controles de §4 estén en verde. Si en `web/` chocan, `ponytail` decide el alcance (qué se construye) e `impeccable` y los skills de diseño deciden el acabado de lo que sí se construye: recortar accesibilidad, estados vacíos o de error no es «ser lazy», es dejar la pantalla a medias. `sqlalchemy` y `pydantic` son de referencia (`disable-model-invocation: true`): leelos con Read, no se invocan como skill.

**No existe un skill `graphify`.** Las reglas del knowledge graph están en AGENTS.md §1 y en `.agents/rules/graphify.md`; para regenerarlo usá `/graph-refresh`. Sin el CLI, `python scripts/code_map.py` (AGENTS.md §1, paso 2).

**Hooks** (`.claude/settings.json`):
- PreToolUse `Bash` y `Grep` → `pretooluse_bash_grep_hint.py`: con el CLI de graphify, el grafo y el transcript, **bloquea (exit 2) la primera búsqueda de texto de la sesión** hasta que se haya consultado el grafo (`graphify query`, `explain` o `path`, por Bash o por MCP); después grep y rg quedan libres. Solo cuenta una llamada a herramienta, no el texto que cite «graphify query». Sin CLI, sin grafo o con un transcript que no sabe leer (Codex), avisa como antes: una vez por sesión, y solo si el comando empieza una búsqueda (no un `| grep` de filtro), con `graphify query` o, sin grafo, `scripts/code_map.py`.
- PreToolUse `Bash` → `pretooluse_bash_revision_visual.py`: ante `git commit` o `gh pr create` con ficheros de `web/src/` (preparados o en la rama frente a `origin/master`), avisa sin bloquear de que la revisión visual de `impeccable` es parte del cambio y de que, si no se hizo, hay que decirlo antes.
- PreToolUse `Edit|Write|MultiEdit` → `pretooluse_edit_stale.py`: al tocar un `.py` deja el flag `graphify-out/.graph_stale`; `/graph-refresh` o el hook de Stop lo borran tras un update exitoso.
- Stop → `stop_graph_refresh.py`: con el flag puesto y el CLI disponible, lanza `graphify update .` en un proceso aparte (no retiene el turno) y borra el flag solo si acabó bien y nadie volvió a editar mientras tanto. Un cerrojo (`graphify-out/.refrescando`) evita dos a la vez; la salida del último refresco queda en `graphify-out/`, en el fichero .ultimo_refresco.log.
- PreToolUse `Edit|Write|MultiEdit` → `pretooluse_edit_skills.py`: busca en el transcript de la sesión las llamadas a `Skill` (o el slash-command del usuario) que exige la tabla de **Skills** para la ruta editada y, si falta alguno, bloquea la edición (exit 2) diciendo cuál cargar. Fuera de esas rutas no hace nada, y si no puede leer el transcript deja pasar. Solo Claude Code lo registra: Codex no tiene herramienta `Skill` y lo bloquearía todo; el fichero está en `.codex/hooks/` por la paridad de hooks que verifica `make check-agent-docs`.
- SessionStart → `session_start_contexto.py`: dice qué le falta al checkout (`.venv`, `.env`, `web/node_modules`), lista los PR abiertos y las ramas con commits recientes para no duplicar trabajo, y siembra el grafo en un worktree nuevo.
- SessionStart, PostToolUse `Edit|Write` y Stop → `.claude/skills/impeccable/scripts/impeccable hook`: el detector de diseño de Impeccable revisa los ficheros de UI editados y hace una pasada completa al parar. Si el skill no está, no hace nada. Su configuración vive en `.impeccable/config.json` (el skill con el argumento `hooks status` la muestra).

Los hooks que bloquean se lanzan con `if command -v python …; then python …; else python3 …; fi` y no con `python … || python3 …`: con el `||`, el `exit 2` de bloqueo hace que corra `python3`, que en Windows es el alias de la Microsoft Store, y el código que llega es 49, así que no bloqueaba nada (medido el 2026-11-03).

En un worktree, Claude Code lanza los hooks desde el checkout principal: los hooks Python deducen el checkout real del `cwd` o de la ruta editada, no de dónde vive el script. Por lo mismo, un cambio en un hook no tiene efecto en las sesiones de worktree hasta que el checkout principal lo trae.

**Sesiones remotas (Claude Code web / CI)**: el hook `SessionStart`
(`.claude/hooks/session_start_pg.py`) provisiona Postgres al arrancar la sesión
—cluster local, rol, base, `pg_trgm`/`vector`— y deja `TEST_DATABASE_URL` en
`.env`, de donde `tests/conftest.py` la lee. Con eso **la suite sí se ejecuta**:
`make test-unit` y `make check` son válidos en remoto. Las dependencias Python
del proyecto no vienen preinstaladas: en un `.venv` (el `pip` del sistema no
puede reemplazar paquetes que instaló Debian), `pip install -r
requirements-dev.txt` —trae también los paquetes de producción:
`requirements-dev.in` empieza con `-r requirements.in`— y `pip install -e ".[pliegos]"` (este último lo exigen los
tests de extracción de PDF). `make lock` compila `requirements-dev.txt` con
`--constraint=requirements.txt`: CI prueba las mismas versiones que corre
producción.

El hook es best-effort: si no consigue Postgres lo dice en su mensaje de
arranque, y entonces vuelve a aplicar la regla de AGENTS.md §4 — se reportan
explícitamente los controles no ejecutados en vez de darlos por verdes. El CLI
`graphify` sigue sin estar disponible en remoto: ahí se navega con
`python scripts/code_map.py` (AGENTS.md §1).
