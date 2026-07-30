# Copilot instructions

**Lee primero [AGENTS.md](../AGENTS.md)** — fuente única de instrucciones (navegación, mapa de áreas, invariantes, comandos, workflow). Este archivo solo añade overrides específicos de GitHub Copilot.

## Overrides Copilot

- Para preguntas sobre arquitectura/dónde-está-X, primera acción: `graphify query "<pregunta>"` en terminal (si `graphify-out/graph.json` existe). No hay comando `/graphify` en Copilot Chat: el CLI es una herramienta local del mantenedor, y si no está instalado se leen los artefactos commiteados (`graphify-out/graph.json`, `wiki/`, `GRAPH_REPORT.md`) — ver AGENTS.md §1 para el orden de fallback completo.
- Triggers: "how do I…", "where is…", "what does … do", "add/modify a <component>", "explain the architecture", o cualquier cosa que dependa de cómo se relacionan files/clases.
- Copilot no lee `.claude/commands/` ni `.claude/skills/`: los workflows equivalentes (check, graph-refresh, find-improvements, area) están en la sección 4 de AGENTS.md y se ejecutan como targets `make` o comandos `graphify`. Las reglas de graphify también están en `.agents/rules/graphify.md`.
- Antes de declarar un cambio listo: `make lint && make typecheck && make test-unit`. Los tests exigen Postgres y `TEST_DATABASE_URL` (AGENTS.md §4); si no los tenés, reportá los tests como no ejecutados en vez de omitir el hecho.
