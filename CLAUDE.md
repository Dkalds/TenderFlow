# CLAUDE.md

**Lee primero [AGENTS.md](AGENTS.md)** — fuente única de instrucciones (navegación, mapa de áreas, invariantes, comandos, workflow). Este archivo solo añade overrides específicos de Claude Code.

## Overrides Claude Code

**Slash-commands** (`.claude/commands/`): `/check`, `/graph-refresh`, `/find-improvements`, `/area <nombre>`. Son la fuente canónica de esos cuatro workflows; `.agents/skills/source-command-*/` son copias para otras herramientas y no deben divergir.

**Skills**: Claude Code carga `.claude/skills/` (`.agents/skills/` es para Codex/OpenCode; ambos árboles se instalan desde `skills-lock.json` y deben tener el mismo contenido — `make check-agent-docs` lo verifica). Relevantes para este repo: `fastapi-python`, `python-patterns`, `python-testing-patterns`, `pandas-pro`, `machine-learning`, `scikit-learn`, `supabase-postgres-best-practices`, `sqlalchemy-alembic-expert-best-practices-code-review`. Usalos cuando la tarea encaje. `sqlalchemy` y `pydantic` son de referencia (`disable-model-invocation: true`): leelos con Read, no se invocan como skill.

**No existe un skill `graphify`.** Las reglas del knowledge graph están en AGENTS.md §1 y en `.agents/rules/graphify.md`; para regenerarlo usá `/graph-refresh`. Sin el CLI, `python scripts/code_map.py` (AGENTS.md §1, paso 2).

**Hooks** (`.claude/settings.json`):
- PreToolUse `Bash` → `pretooluse_bash_grep_hint.py`: una vez por sesión, y solo si el comando empieza una búsqueda (no un `| grep` de filtro), recuerda `graphify query` o, sin grafo, `scripts/code_map.py`.
- PreToolUse `Edit|Write|MultiEdit` → `pretooluse_edit_stale.py`: al tocar un `.py` deja el flag `graphify-out/.graph_stale`; `/graph-refresh` lo borra tras un update exitoso.
- SessionStart → `session_start_contexto.py`: dice qué le falta al checkout (`.venv`, `.env`, `web/node_modules`), lista los PR abiertos y las ramas con commits recientes para no duplicar trabajo, y siembra el grafo en un worktree nuevo.

En un worktree, Claude Code lanza los hooks desde el checkout principal: los tres deducen el checkout real del `cwd` o de la ruta editada, no de dónde vive el script. Por lo mismo, un cambio en un hook no tiene efecto en las sesiones de worktree hasta que el checkout principal lo trae.

**Sesiones remotas (Claude Code web / CI)**: el hook `SessionStart`
(`.claude/hooks/session_start_pg.py`) provisiona Postgres al arrancar la sesión
—cluster local, rol, base, `pg_trgm`/`vector`— y deja `TEST_DATABASE_URL` en
`.env`, de donde `tests/conftest.py` la lee. Con eso **la suite sí se ejecuta**:
`make test-unit` y `make check` son válidos en remoto. Las dependencias Python
del proyecto no vienen preinstaladas: `pip install -r requirements.txt -r
requirements-dev.txt` y `pip install -e ".[pliegos]"` (este último lo exigen los
tests de extracción de PDF).

El hook es best-effort: si no consigue Postgres lo dice en su mensaje de
arranque, y entonces vuelve a aplicar la regla de AGENTS.md §4 — se reportan
explícitamente los controles no ejecutados en vez de darlos por verdes. El CLI
`graphify` sigue sin estar disponible en remoto: ahí se navega con
`python scripts/code_map.py` (AGENTS.md §1).
