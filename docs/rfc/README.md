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
| `superseded` | — | La decisión se mudó a otro documento vivo —otro RFC o un ADR— que se cita en `superseded_by` |
| `implemented` | — | Implementado y verificado en código (todos los acceptance criteria cumplidos) |
| `partially-implemented` | — | Criterio/bug central implementado y verificado; criterios secundarios diferidos (ver notas de review) |
| `obsolete` | — | Ya no aplica (problema desaparecido o resuelto por otra vía) |

---

## Qué significa `implemented` (criterio explícito)

**Un RFC pasa a `implemented` cuando el código existe en el árbol, no cuando su
PR aparece mergeado.** Son cosas distintas y confundirlas es lo que dejó los RFC
de la tabla de abajo con el `status` que tenían el día que se escribieron, aunque
su código llevara semanas o meses en `master`: el retrofit de PLACSP entró el
2026-07-05 (`1b1a759`) y el guardarraíl del meta-RFC de integridad analítica pasó
a bloqueante el 2026-07-28 (`3ed8b7f`); los dos seguían en `accepted`/`draft` el
2026-09-06. El PR se mergea, se revierte a medias, se renombra el módulo o el
trabajo entra por otra rama, y el front matter se queda donde estaba porque nadie
lo mira al cerrar el PR.

En la práctica:

1. Se localiza en el árbol lo que el RFC prometía —el módulo, la revisión
   Alembic, la ruta, el guardarraíl de CI— con un comando que se pueda repetir.
2. Se anota en el front matter `implemented_on` (fecha de la comprobación) y
   `implemented_evidence` (qué se encontró y dónde). La evidencia es la parte que
   importa: sin ella, el estado vuelve a ser una afirmación sin respaldo.
3. Si lo prometido no está entero, el estado es `partially-implemented` y la
   evidencia dice qué falta. No hay estado intermedio optimista.

`obsolete` sigue el mismo criterio por el otro lado: se marca cuando se comprueba
que los ficheros o superficies que el RFC ataca **ya no existen**, con el comando
que lo demuestra en `obsolete_reason`. Y `superseded` cuando la decisión se mudó a
otro documento vivo (típicamente un ADR), citándolo en `superseded_by`.

No hay índice de estados mantenido a mano en este README: el front matter de cada
fichero es la fuente. Para listar los que siguen abiertos:

```sh
grep -lE "^status: (draft|review|approved) *$" docs/rfc/*.md
```

El `$` no es cosmético: sin él la plantilla de este mismo README —cuya línea
`status:` enumera los ocho estados posibles— sale en la lista como si fuera un
RFC abierto.

---

## Reconciliación del 2026-09-06

Barrido del hecho 25 del [plan de arquitectura 2026-09 v2](../plans/2026-09-plan-arquitectura-v2.md)
(ítem O0.7b). Se comprobó en el árbol cada RFC antes de tocar su `status`; la
evidencia concreta está en el front matter de cada fichero.

| RFC | Estado | Comprobado en el código |
|---|---|---|
| [242-acceso-oauth-dinamico](242-acceso-oauth-dinamico.md) | `implemented` | `v95_access_grants`, `db/access_grants.py`, rutas `/grants` de `api/routes/admin_solicitudes.py` |
| [243-recuperacion-contrasena-local](243-recuperacion-contrasena-local.md) | `implemented` | `v96_password_reset_tokens`, `/password-reset/{request,confirm}` en `api/routes/auth.py` |
| [2026-09-02-rfc-enlaces-firmados-sin-sesion](2026-09-02-rfc-enlaces-firmados-sin-sesion.md) | `implemented` | `shared/signing.py` (con `kid`), enlace firmado del ICS en `api/routes/exports.py`, baja firmada en `services/email_digest.py` |
| [2026-06-30-rfc-retrofit-pipeline-placsp-connector](2026-06-30-rfc-retrofit-pipeline-placsp-connector.md) | `implemented` | `PlacspAtomConnector` y `PlacspBulkConnector` en `scraper/connectors/placsp.py` |
| [2026-06-16-rfc-meta-integridad-analitica-frontend](2026-06-16-rfc-meta-integridad-analitica-frontend.md) | `superseded` | Graduó a [ADR-014](../adr/ADR-014-integridad-analitica-frontend.md); el guardarraíl es `scripts/check_frontend_invariants.py --strict`, bloqueante en `ci.yml` |
| [2026-07-21-rfc-relaciones-estructura-mercado](2026-07-21-rfc-relaciones-estructura-mercado.md) | `obsolete` | Las tres superficies que rediseñaba ya no existen en `web/src` |
| [2026-09-06-rfc-retirada-endpoints-analitica](2026-09-06-rfc-retirada-endpoints-analitica.md) | `approved` | Retirada anunciada de D19; efectiva el 2026-12-04. Las cuatro operaciones ya salen `deprecated` en el OpenAPI |
