---
rfc: 2026-06-30
title: LLM como dependencia gestionada — presupuesto, circuit-breaker, fallback degradado y eval de RAG
issue: pendiente — generado en sesión de arquitectura (revisión integral 2026-06-30); sin issue asociado aún
author: agent:architect
date: 2026-06-30
status: draft
---

## Contexto

El endpoint `/ask` (RAG + SSE streaming, `api/routes/ask.py`) pasó de ser un
extra opcional a un **camino de producción con un proveedor externo de pago**.
La conexión a NVIDIA NIM/DeepSeek (commit `d6619f8`) lo consolida como dependencia
crítica: latencia variable, coste por request y disponibilidad fuera de nuestro
control.

El RFC 2026-06-17 ("Observabilidad de tokens y coste en el cliente LLM",
status `implemented`) cerró la **medición** —`llm_tokens_total`,
`llm_cost_usd_total`— y dejó explícitamente fuera de alcance la **política**:

> *"No se añade presupuesto/budget enforcement (cortar requests al superar un
> umbral de coste). Esto es medir antes de actuar; el enforcement sería un RFC
> posterior una vez haya datos."*

Este es ese RFC posterior. Con la métrica ya en producción, ahora el riesgo es que
una dependencia de pago, externa y en el camino crítico **no tenga guardrails**:

1. **Sin presupuesto/circuit-breaker de gasto**: un cliente abusando de `/ask`, un
   prompt que crece sin control o un bug de bucle pueden disparar el coste sin
   tope. Hoy se mide el gasto pero nada lo corta.
2. **Sin fallback degradado**: si NVIDIA NIM cae o agota cuota, `/ask` falla. No
   hay un modo "búsqueda sin síntesis LLM" que mantenga el valor mínimo.
3. **Sin evaluación de calidad de RAG**: sin un eval set, las regresiones de
   calidad de respuesta (cambio de modelo, de prompt, de chunking de contexto) son
   **invisibles** — no las cubre ningún test. Un cambio que empeora las respuestas
   pasa CI en verde.

ADR-006 ya estableció rate-limit Redis para endpoints pesados (`/ask` incluido),
que protege *frecuencia* pero no *gasto acumulado* ni *calidad*.

## Decisión

Tratar el LLM como una **dependencia gestionada** con tres guardrails, aditivos y
sin cambiar el contrato público de `stream_llm_response` ni el DTO de `/ask`:

1. **Presupuesto + circuit-breaker de coste** (`llm/budget.py`):
   - Tope de gasto configurable por ventana (`LLM_BUDGET_USD_DAILY`,
     `LLM_BUDGET_USD_MONTHLY` en `config/settings.py`), alimentado por el
     `llm_cost_usd_total` que ya existe.
   - Al superar el umbral: el cliente **rechaza con un error tipado**
     (`LLMBudgetExceeded`) que `/ask` traduce a `429`/`503` con mensaje claro, en
     vez de seguir gastando. Estado del breaker en Redis (consistente con ADR-006),
     con fallback in-memory si Redis ausente.
   - Métrica `llm_budget_exceeded_total` para alertar.

2. **Fallback degradado** (`api/routes/ask.py`):
   - Si el proveedor falla (timeout, 5xx, cuota) **o** el breaker está abierto,
     `/ask` degrada a **resultados de búsqueda sin síntesis LLM** —los mismos
     documentos que alimentan el RAG, devueltos como lista— marcando la respuesta
     con un flag `degraded: true` en el stream (sin romper el contrato SSE: es un
     evento, no un cambio de DTO).
   - El usuario recibe valor (las licitaciones relevantes) aunque no la prosa.

3. **Eval set de RAG en CI** (`tests/eval/`):
   - Un set pequeño y versionado de `(pregunta, contexto esperado, aserciones)` que
     valida **recuperación** (¿el chunk correcto entró al contexto?) de forma
     determinista, sin llamar al LLM real (mock del generador). La calidad de la
     *generación* se evalúa offline con un runner opcional (`make eval-llm`) que sí
     llama al proveedor, fuera del gate de CI por coste/no-determinismo.
   - Gate CI: la **recuperación** no regresiona (es determinista y barata). La
     generación es un check manual/periódico.

**Qué NO se hace:**

- **No** se cambia el DTO Pydantic de `/ask` (§3.5): el flag `degraded` viaja como
  evento SSE, no como campo del contrato.
- **No** se mete un eval de generación LLM en el gate de CI (no determinista,
  cuesta dinero por run) — vive en un runner opcional.
- **No** se cachean respuestas LLM en este RFC (es una optimización de coste
  separada; aquí el foco es *no gastar de más* y *no caer*).
- **No** se refresca `AVAILABLE_MODELS` (ítem ya flaggeado por el RFC de tokens).

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Solo rate-limit (ADR-006), sin budget | Ya existe | Limita frecuencia, no gasto acumulado ni picos de un solo prompt caro | Insuficiente para una dependencia de pago |
| Budget enforcement en el reverse-proxy/API gateway | Desacopla del código | No tiene la señal de coste por token (vive en el cliente LLM); difícil de degradar elegante | El cliente es donde está el dato y el punto de degradación |
| Fallback a otro proveedor LLM | Resiliencia total | Multiplica credenciales/coste/complejidad; otro proveedor también puede caer | Sobredimensionado; degradar a búsqueda cubre el valor mínimo |
| Eval de generación con LLM-judge en CI | Mide calidad real | No determinista, costoso por run, flaky | Va al runner opcional, no al gate |
| Sin eval, confiar en review manual | Cero trabajo | Las regresiones de RAG son invisibles hasta producción | Es el punto ciego que el RFC cierra |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | `llm/` y `api/` son strict; código nuevo nace strict | `LLMBudgetExceeded`, `Budget` tipados |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno — el estado del breaker vive en Redis, no en schema | — |
| §3.4 Auto-marking tests | Ninguno — eval set bajo `tests/eval/` con naming | — |
| §3.5 Pydantic v2 DTOs | **Ninguno** — `degraded` es evento SSE, no campo del DTO | Decisión explícita de no tocar el contrato |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. `config/settings.py` — `LLM_BUDGET_USD_DAILY`/`_MONTHLY`, `LLM_BUDGET_MODE`
   (`enforce`|`monitor`). Default `monitor` (no corta) para rodaje, igual que el
   CSP Report-Only de fase 1.
2. `llm/budget.py` — acumulador sobre `llm_cost_usd_total`, breaker en Redis con
   fallback in-memory, error `LLMBudgetExceeded`, métrica `llm_budget_exceeded_total`.
3. `llm/client.py` — consultar el breaker antes de iniciar el stream; lanzar el
   error tipado si está abierto.
4. `api/routes/ask.py` — capturar fallo del proveedor / breaker abierto → emitir
   evento SSE `degraded` + lista de documentos del RAG sin síntesis.
5. `tests/eval/` — set de recuperación determinista (mock del generador) en el gate
   de CI; `make eval-llm` runner opcional para generación.
6. `observability/` — alerta de `llm_budget_exceeded_total` y de tasa de respuestas
   `degraded`.

**Archivos de partida**: `api/routes/ask.py`, `llm/client.py`,
`llm/providers/openai_provider.py`, `llm/providers/anthropic_provider.py`,
`config/settings.py`, `docs/adr/ADR-006-etag-pdf-export-ratelimit-redis.md`.
**Riesgo estimado**: medio — toca un endpoint de producción, mitigado por
`LLM_BUDGET_MODE=monitor` como default (medir antes de cortar) y por mantener el
contrato API intacto.
**Tiempo estimado**: 1.5–2.5 días.

## Acceptance criteria

- [ ] Con `LLM_BUDGET_MODE=enforce` y presupuesto superado, `/ask` responde
      429/503 con mensaje claro y **no** llama al proveedor; `llm_budget_exceeded_total` sube.
- [ ] Con `monitor`, solo se alerta (no se corta), validado con test.
- [ ] Ante fallo del proveedor o breaker abierto, `/ask` degrada a documentos del
      RAG sin síntesis, marcado `degraded` en el stream; el SSE no rompe.
- [ ] El eval de **recuperación** corre determinista en CI sin llamar al LLM real y
      falla si un cambio rompe el contexto recuperado.
- [ ] El DTO Pydantic de `/ask` no cambia (§3.5).
- [ ] `make lint && make typecheck && make test-unit` pasan en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<Comentarios del reviewer y security_triage durante la etapa agent:rfc-review.
Formato: `YYYY-MM-DDTHH:MMZ agent:reviewer — <comentario>`>
