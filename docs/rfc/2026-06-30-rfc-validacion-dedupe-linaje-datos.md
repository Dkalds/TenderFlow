---
rfc: 2026-06-30
title: Validación de la precisión del dedupe cross-fuente y linaje de datos como contrato testeable
issue: pendiente — generado en sesión de arquitectura (revisión integral 2026-06-30); sin issue asociado aún
author: agent:architect
date: 2026-06-30
status: draft
---

## Contexto

Con multi-fuente activo ([[ADR-009-framework-conectores-multifuente|ADR-009]]: PLACSP + `ted` + `pscp` + `tacrc`), el riesgo de
calidad de datos se **desplaza**. Antes era *"¿extrajimos el campo?"* —cubierto por
los SLO de cobertura (importe ≥80%) y las métricas de NULL del parser
(`parser_field_null_total`, backlog 2026-06-10). Ahora el riesgo dominante es
*"¿es correcto el dato fusionado entre fuentes?"*.

[[ADR-009-framework-conectores-multifuente|ADR-009]] Fase 5.2 introdujo dedupe cross-fuente: un contrato que aparece en PLACSP
*y* TED se marca en `licitaciones_duplicados` (`services/dedupe.py`) con clave débil
**órgano normalizado + expediente nacional + CPV-4**, y las consultas analíticas lo
excluyen vía `exclude_duplicados_sql()`. Hay un guardrail —`tests/test_dedup_guardrail.py`—
que falla en CI si una query analítica nueva **omite el filtro** de duplicados.

El problema: ese guardrail protege que las queries *apliquen* el filtro, **no que el
matching sea correcto**. Y la asimetría de coste de un error de matching es severa:

- **Falso positivo** (marca como duplicadas dos licitaciones que son distintas):
  **borra una licitación real** del análisis de competencia. El producto es
  precisamente ese análisis → un FP es una pérdida silenciosa de señal de negocio.
- **Falso negativo** (no detecta un duplicado real): doble conteo, infla volúmenes
  y cuotas de mercado.

Una clave débil basada en normalización de strings (órgano + expediente + CPV-4) es
exactamente el tipo de heurística que funciona en el 95% y falla en los casos borde
—y nadie se entera, porque **no hay medición de su precisión/recall**. Hoy el dedupe
es código sin red de evaluación.

## Decisión

Convertir la **correctitud del dedupe** y el **linaje del dato fusionado** en un
contrato testeable, con tres componentes:

1. **Golden set de dedupe etiquetado a mano** (`tests/fixtures/dedupe_golden.jsonl`):
   un conjunto curado de pares de licitaciones cross-fuente con etiqueta humana
   (`duplicate` | `distinct`), incluyendo casos borde reales (mismo órgano distinto
   contrato, mismo contrato distinto CPV-4 por reclasificación, expedientes con
   formato divergente entre PLACSP y autonómicas). Se versiona y crece cuando
   aparece un error en producción (cada incidente añade su caso).

2. **Test de precisión/recall en CI** (`tests/test_dedupe_quality.py`):
   corre `services/dedupe.py` sobre el golden set y mide precision/recall del
   matching. Gates: **precision ≥ umbral alto** (un FP borra datos reales — es el
   error caro) y recall reportado. El umbral se fija con el golden set inicial y
   **no puede bajar** sin justificación en review (regla anti-regresión, igual que
   los thresholds de coverage).

3. **Linaje explícito y reversibilidad auditable**:
   - El marcado en `licitaciones_duplicados` ya es reversible ([[ADR-009-framework-conectores-multifuente|ADR-009]]). Añadir
     que registre **por qué** se marcó (la clave que hizo match) para auditoría —
     trazabilidad de "esta fila se ocultó por este criterio".
   - Métrica `dedupe_marked_total{source_pair}` y `dedupe_match_rate` para alertar
     si una corrida marca un volumen anómalo (un cambio de normalización que de
     golpe duplica el rate es una regresión de matching detectable en vivo).

**Qué NO se hace:**

- **No** se cambia la clave de matching ni el algoritmo de `services/dedupe.py` en
  este RFC — primero se **mide** la calidad de la heurística actual. Si el golden
  set revela que la precisión es insuficiente, *eso* dispara un RFC de mejora del
  algoritmo (fuzzy matching, embeddings de título, etc.), con baseline para
  comparar.
- **No** se toca `tests/test_dedup_guardrail.py` (cubre otra cosa: que las queries
  filtren; sigue válido y complementario).
- **No** se introduce ML/embeddings para el matching ahora — sería prematuro sin
  la medición que justifique el coste.
- **No** se cambia el contrato API ni los DTOs.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo (solo guardrail de filtro) | Ya existe | No mide si el matching acierta; los FP borran datos reales sin detección | Es el punto ciego que el RFC cierra |
| Mejorar el algoritmo de matching ya (fuzzy/embeddings) | Quizá más preciso | Sin baseline no se puede saber si mejora o empeora; optimización a ciegas | Hay que medir antes de cambiar |
| Solo métrica en vivo (`dedupe_match_rate`), sin golden set | Barato | Detecta cambios bruscos pero no la corrección absoluta; no hay verdad de referencia | Necesario pero insuficiente sin etiquetas |
| Revisión manual periódica de duplicados | Cero código | No escala, no es gate, no previene regresión | No es un contrato testeable |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | `services/` strict; test/código nuevo nace strict | — |
| §3.2 Upsert idempotente | Ninguno — el dedupe marca, no reescribe filas fuente | El marcado sigue siendo reversible ([[ADR-009-framework-conectores-multifuente|ADR-009]]) |
| §3.3 Migraciones append-only | Posible: columna de "criterio de match" en `licitaciones_duplicados` → nueva revisión Alembic | OK humano antes de tocar `db/alembic/**` (§6) |
| §3.4 Auto-marking tests | Ninguno — `test_dedupe_quality.py` sigue naming | — |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. `tests/fixtures/dedupe_golden.jsonl` — golden set inicial etiquetado a mano
   (semilla con casos PLACSP↔TED y casos borde conocidos).
2. `tests/test_dedupe_quality.py` — corre `services/dedupe.py` sobre el golden set,
   mide precision/recall, gate de precision ≥ umbral anti-regresión.
3. `services/dedupe.py` — registrar el criterio de match al marcar (linaje);
   exponer `dedupe_marked_total{source_pair}` / `dedupe_match_rate`.
4. `observability/alert_rules.yml` — alerta si `dedupe_match_rate` se desvía
   bruscamente de su baseline.
5. (Si aplica) migración Alembic para la columna de criterio en
   `licitaciones_duplicados` — **requiere OK humano**.
6. `docs/adr/[[ADR-009-framework-conectores-multifuente|ADR-009]]-framework-conectores-multifuente.md` — nota: la calidad del
   dedupe ahora tiene contrato de test (referencia a este RFC).

**Archivos de partida**: `services/dedupe.py`, `tests/test_dedup_guardrail.py`,
`docs/adr/[[ADR-009-framework-conectores-multifuente|ADR-009]]-framework-conectores-multifuente.md`,
`observability/alert_rules.yml`, `observability/runtime_metrics.py`.
**Riesgo estimado**: bajo — aditivo (tests + métricas + linaje); no cambia el
algoritmo de matching ni el camino de datos. El único punto sensible es la
eventual migración de schema, gateada por OK humano.
**Tiempo estimado**: 1.5–2 días (mayoría en curar el golden set).

## Acceptance criteria

- [ ] Existe `tests/fixtures/dedupe_golden.jsonl` con casos `duplicate`/`distinct`
      etiquetados a mano, incluyendo casos borde.
- [ ] `tests/test_dedupe_quality.py` mide precision/recall sobre el golden set y
      falla en CI si la precision baja del umbral fijado.
- [ ] `services/dedupe.py` registra el criterio que produjo cada match (linaje
      auditable y reversible).
- [ ] `dedupe_match_rate` se expone y tiene alerta de desviación.
- [ ] El umbral de precision no puede bajar sin justificación en review.
- [ ] `make lint && make typecheck && make test-unit` pasan en verde.

## Notas de review

<Comentarios del reviewer y security_triage durante la etapa agent:rfc-review.
Formato: `YYYY-MM-DDTHH:MMZ agent:reviewer — <comentario>`>
