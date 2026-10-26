# Copilot instructions

**Lee primero [AGENTS.md](../AGENTS.md)** — fuente única de instrucciones (navegación, mapa de áreas, invariantes, comandos, workflow). Este archivo solo añade overrides específicos de GitHub Copilot.

## Overrides Copilot

- Para preguntas sobre arquitectura/dónde-está-X, seguí el orden de AGENTS.md §1: usa Graphify CLI o MCP local cuando estén disponibles; si no, usa `python scripts/code_map.py` (`simbolo`, `importadores`, `paquete`, `fichero`) para código Python y búsqueda textual para el resto. Graphify es opcional; no lo añadas a las dependencias del proyecto.
- Triggers: "how do I…", "where is…", "what does … do", "add/modify a <component>", "explain the architecture", o cualquier cosa que dependa de cómo se relacionan files/clases.
- Copilot no lee `.claude/commands/` ni `.claude/skills/`: los workflows portables están en `.agents/skills/source-command-*/` y los comandos del proyecto en el Makefile. Las reglas de Graphify también están en `.agents/rules/graphify.md`.
- Antes de declarar un cambio listo: `make lint && make typecheck && make test-unit`. Los tests exigen Postgres y `TEST_DATABASE_URL` (AGENTS.md §4); si no los tenés, reportá los tests como no ejecutados en vez de omitir el hecho.
