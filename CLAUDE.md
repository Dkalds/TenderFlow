# CLAUDE.md

**Lee primero [AGENTS.md](AGENTS.md)** — fuente única de instrucciones (navegación, mapa de áreas, invariantes, comandos, workflow). Este archivo solo añade overrides específicos de Claude Code.

## Overrides Claude Code

- Slash-commands disponibles en `.claude/commands/`: `/check`, `/graph-refresh`, `/find-improvements`, `/area <nombre>`.
- Skills custom en `.agents/skills/` (machine-learning, pandas-pro, sqlalchemy, fastapi-python, etc.) — usalos cuando la tarea encaje.
- Cuando el usuario tipea `/graphify`, invocá el skill tool con `skill: "graphify"` antes de cualquier otra cosa.
- Hooks activos en `.claude/settings.json`: PreToolUse inyecta recordatorio de usar `graphify query` cuando intentás grep.
