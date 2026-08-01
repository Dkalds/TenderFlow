# CLAUDE.md

**Lee primero [AGENTS.md](AGENTS.md)** — fuente única de instrucciones (navegación, mapa de áreas, invariantes, comandos, workflow). Este archivo solo añade overrides específicos de Claude Code.

## Overrides Claude Code

**Slash-commands** (`.claude/commands/`): `/check`, `/graph-refresh`, `/find-improvements`, `/area <nombre>`. Son la fuente canónica de esos cuatro workflows; `.agents/skills/source-command-*/` son copias para otras herramientas y no deben divergir.

**Skills**: Claude Code carga `.claude/skills/` (`.agents/skills/` es para Codex/OpenCode; ambos árboles se instalan desde `skills-lock.json` y deben tener el mismo contenido — `make check-agent-docs` lo verifica). Relevantes para este repo: `fastapi-python`, `python-patterns`, `python-testing-patterns`, `pandas-pro`, `machine-learning`, `scikit-learn`, `supabase-postgres-best-practices`, `sqlalchemy-alembic-expert-best-practices-code-review`. Usalos cuando la tarea encaje. `sqlalchemy` y `pydantic` son de referencia (`disable-model-invocation: true`): leelos con Read, no se invocan como skill.

**No existe un skill `graphify`.** Las reglas del knowledge graph están en AGENTS.md §1 y en `.agents/rules/graphify.md`; para regenerarlo usá `/graph-refresh`.

**Hooks** (`.claude/settings.json`, ambos PreToolUse):
- `Bash` → `pretooluse_bash_grep_hint.py`: recuerda usar `graphify query` antes de grep.
- `Edit|Write|MultiEdit` → `pretooluse_edit_stale.py`: al tocar un `.py` deja el flag `graphify-out/.graph_stale`; `/graph-refresh` lo borra tras un update exitoso.

**Sesiones remotas (Claude Code web / CI)**: no hay Postgres ni `TEST_DATABASE_URL`, así que `make test-unit` aborta al arrancar y el CLI `graphify` no está instalado. Ver AGENTS.md §4 y la matriz de prerrequisitos de `docs/AGENT_PLAYBOOK.md` antes de declarar un cambio verde: lint y typecheck sí corren, los tests no, y eso se reporta explícitamente en vez de omitirse.
