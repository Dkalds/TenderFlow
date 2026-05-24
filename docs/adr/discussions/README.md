# ADR Discussions — licitaciones-sap

Log append-only de discusiones inter-agente durante el ciclo de vida de issues y RFCs.

## Propósito

Cada vez que el Orchestrator cierra un issue procesado, vuelca el thread completo de comentarios GitHub aquí como registro permanente. Esto permite:

- Auditar las decisiones tomadas por los agentes.
- Aprender de iteraciones anteriores.
- Detectar patrones de errores recurrentes.

## Nombre de archivo

`docs/adr/discussions/NNN-slug.md`

Donde `NNN` es el número de issue y `slug` es el título sanitizado del issue.

---

## Formato de cada entrada

```markdown
---
issue: NNN
title: <título del issue>
url: <URL del issue de GitHub>
rfc: <URL del RFC si aplica>
opened: YYYY-MM-DD
closed: YYYY-MM-DD
result: merged | blocked | rejected | cancelled
pr: <URL del PR si aplica>
agents_involved:
  - orchestrator
  - architect
  - coder
  - test_engineer
  - reviewer
  - security_triage
---

# Discussion: <título del issue>

## Timeline

### YYYY-MM-DDTHH:MMZ agent:orchestrator
<turno del orchestrator>

### YYYY-MM-DDTHH:MMZ agent:architect
<turno del architect>

### YYYY-MM-DDTHH:MMZ agent:reviewer
<turno del reviewer>

...

## Resultado

<Resumen de lo que se implementó, por qué se aprobó/rechazó, lecciones aprendidas.>
```

---

## Convenciones

- **Append-only**: nunca modificar una entrada existente. Si hay correcciones, agregar nueva entrada al final.
- **Formato de turno**: `## YYYY-MM-DDTHH:MMZ <agente>` (ISO 8601 con Z para UTC).
- **El Orchestrator** es el responsable de crear el archivo al cerrar el issue.
- **Un archivo por issue**. Si el issue se reabre, la nueva discusión se agrega al mismo archivo con separador `---`.
