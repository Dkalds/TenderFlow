# Copilot instructions

**Lee primero [AGENTS.md](../AGENTS.md)** — fuente única de instrucciones (navegación, mapa de áreas, invariantes, comandos, workflow). Este archivo solo añade overrides específicos de GitHub Copilot.

## Overrides Copilot

- Para preguntas sobre arquitectura/dónde-está-X, seguí el orden de AGENTS.md §1: usa `graphify query "<pregunta>"` solo si el CLI está disponible; de lo contrario consulta los artefactos commiteados (`graphify-out/graph.json`, `wiki/`, `GRAPH_REPORT.md`). No hay comando `/graphify` en Copilot Chat y el CLI no debe instalarse.
- Triggers: "how do I…", "where is…", "what does … do", "add/modify a <component>", "explain the architecture", o cualquier cosa que dependa de cómo se relacionan files/clases.
- Copilot no lee `.claude/commands/` ni `.claude/skills/`: los workflows portables están en `.agents/skills/source-command-*/` y los comandos del proyecto en el Makefile. Las reglas de Graphify también están en `.agents/rules/graphify.md`.
- Antes de declarar un cambio listo: `make lint && make typecheck && make test-unit`. Los tests exigen Postgres y `TEST_DATABASE_URL` (AGENTS.md §4); si no los tenés, reportá los tests como no ejecutados en vez de omitir el hecho.
