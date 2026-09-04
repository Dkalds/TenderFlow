# RFC Format — licitaciones-sap

Todos los RFCs siguen esta estructura.

> **Sobre los roles de agente (corregido el 2026-09-03).** Este README decía que
> «el agente **architect** es responsable de producirlos», y la plantilla de
> abajo sigue admitiendo `author: agent:architect`. Ese esquema multi-rol
> (orchestrator, architect, coder, test_engineer, reviewer, security_triage) se
> **retiró el 2026-07-30** junto con la denylist por rol que lo sostenía: hoy no
> hay roles, hay agentes que siguen `AGENTS.md`. El campo `author` se conserva
> por compatibilidad con los RFCs ya escritos —y porque `docs/adr/discussions/`
> hay que leerlo con esa clave—, pero en un RFC nuevo se pone quién lo escribió
> de verdad. Quién produce un RFC y cuándo hace falta está en `AGENTS.md` §5, no
> aquí.

## Nombre de archivo

`docs/rfc/NNN-slug-descriptivo.md`

Donde `NNN` es el número de issue de GitHub con padding a 3 dígitos (ej: `042-documentar-facade-db.md`).

---

## Plantilla

```markdown
---
rfc: NNN
title: <título descriptivo>
issue: <URL del issue de GitHub>
author: <agent:architect | human:nombre>
date: YYYY-MM-DD
status: draft | review | approved | rejected | superseded | implemented | partially-implemented | obsolete
supersedes: <RFC anterior si aplica>
---

## Contexto

<¿Por qué se necesita este cambio? ¿Qué problema resuelve? Referencias a ADRs relevantes.>

## Decisión

<La decisión técnica propuesta, descrita con precisión. Qué se hace, qué NO se hace.>

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| ... | ... | ... | ... |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Ninguno / Afecta módulo X | ... |
| §3.2 Upsert idempotente | Ninguno / Nueva operación Y | ... |
| §3.3 Migraciones append-only | Ninguno / Nueva migración Z | ... |
| §3.4 Auto-marking tests | Ninguno | — |
| §3.5 Pydantic v2 DTOs | Ninguno / Campo W cambia | ... |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. <Paso 1 — archivo(s) afectados>
2. <Paso 2>
3. ...

**Archivos de partida**: `<lista de archivos relevantes>`
**Riesgo estimado**: bajo | medio | alto
**Tiempo estimado**: <N horas/días>

## Acceptance criteria

- [ ] <Criterio verificable 1>
- [ ] <Criterio verificable 2>
- [ ] `make lint && make typecheck && make test-unit` pasan en verde
- [ ] diff-cover ≥ 80% en líneas nuevas

## Notas de review

<Comentarios del reviewer y security_triage durante la etapa agent:rfc-review.
Formato: `YYYY-MM-DDTHH:MMZ agent:reviewer — <comentario>`>
```

---

## Estados del ciclo de vida

| Status | Label de issue | Significado |
|---|---|---|
| `draft` | `agent:rfc-draft` | Generado por architect, pendiente de review |
| `review` | `agent:rfc-review` | Bajo revisión de reviewer + test_engineer |
| `approved` | `agent:rfc-approved` | Listo para que el coder implemente |
| `rejected` | — | Descartado con justificación |
| `superseded` | — | Reemplazado por otro RFC (ver campo `supersedes`) |
| `implemented` | — | Implementado y verificado en código (todos los acceptance criteria cumplidos) |
| `partially-implemented` | — | Criterio/bug central implementado y verificado; criterios secundarios diferidos (ver notas de review) |
| `obsolete` | — | Ya no aplica (problema desaparecido o resuelto por otra vía) |
