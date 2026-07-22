# Copilot instructions

**Lee primero [AGENTS.md](../AGENTS.md)** — fuente única de instrucciones (navegación, mapa de áreas, invariantes, comandos, workflow). Este archivo solo añade overrides específicos de GitHub Copilot.

## Overrides Copilot

- Type `/graphify` en Copilot Chat para construir o actualizar el knowledge graph.
- Para preguntas sobre arquitectura/dónde-está-X, primera acción: `graphify query "<pregunta>"` (si existe `graphify-out/graph.json`).
- Triggers: "how do I…", "where is…", "what does … do", "add/modify a <component>", "explain the architecture", o cualquier cosa que dependa de cómo se relacionan files/clases.
- Copilot no lee `.claude/commands/`: los workflows equivalentes (check, graph-refresh, find-improvements, area) están documentados en la sección 4 de AGENTS.md y se pueden ejecutar manualmente como `make` targets o comandos `graphify`.
