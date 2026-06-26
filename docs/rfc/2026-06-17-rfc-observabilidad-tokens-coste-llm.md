---
rfc: 2026-06-17
title: Observabilidad de tokens y coste en el cliente LLM
issue: pendiente — generado por /loop (identificación autónoma de mejoras); sin issue asociado aún
author: agent:architect
date: 2026-06-17
status: implemented
---

## Contexto

El feature `/ask` (RAG + SSE streaming, ver backlog 2026-05-23 "Bloque 6") consume
proveedores LLM de pago (`llm/providers/openai_provider.py`,
`llm/providers/anthropic_provider.py`) a través del cliente unificado
`llm/client.py::stream_llm_response`.

Hoy el cliente instrumenta **latencia** —`llm_request_duration_seconds`
(Histogram, labels `model`/`provider`/`status`)— pero **no mide consumo de tokens
ni coste**. Esto deja un hueco en una superficie que cuesta dinero real:

- No se puede responder "¿cuánto gastamos en `/ask` este mes?" ni alertar sobre un
  pico de coste (p. ej. un cliente abusando del endpoint, un prompt que crece sin
  control, o un cambio de modelo más caro).
- No hay atribución por modelo/proveedor: imposible comparar coste-efectividad de
  `gpt-4o-mini` vs `claude-haiku-4-5`.
- La única señal de tamaño que existe es `estimated_tokens = len(prompt) // 4`,
  logueada a nivel **DEBUG** en cada proveedor. Es solo **input**, es una heurística
  burda, y al ser DEBUG no agrega ni alimenta dashboards.

Lo notable es que **el dato real ya está disponible** en ambos SDKs y se está
descartando:

- **Anthropic**: `client.messages.stream(...)` expone
  `stream_obj.get_final_message().usage` con `input_tokens` / `output_tokens`
  tras consumir el stream. Hoy se ignora (`anthropic_provider.py:124-133`).
- **OpenAI**: el streaming de `chat.completions.create(...)` **no** devuelve usage
  por defecto, pero con `stream_options={"include_usage": True}` el último chunk
  llega con `choices == []` y `chunk.usage` poblado
  (`prompt_tokens`/`completion_tokens`). Hoy no se pide ese flag
  (`openai_provider.py:122-132`). El loop actual ya descarta de forma segura los
  chunks sin `choices` (`if chunk.choices else None`), así que el chunk final de
  usage es compatible con el código existente.

Encaja con la cultura de observabilidad ya establecida: el proyecto tiene
contadores Prometheus por todos lados (`ml_inference_duration_seconds`,
`parser_field_null_total`, `scheduler_job_total`, métricas de SQLite BUSY de
ADR-004). Falta cerrar el LLM. Relacionado: ADR-006 (rate-limit Redis para
endpoints pesados), backlog 2026-06-09 "B11" (hardening del cliente LLM).

## Decisión

Capturar el consumo **real** de tokens de ambos proveedores y exponerlo como
métricas Prometheus, más un coste derivado de una tabla de precios estática.
**El sitio de registro de métricas sigue siendo el cliente** (`llm/client.py`),
igual que la latencia hoy; los proveedores solo *producen* el dato.

Cambios concretos:

1. **Sink de usage en los proveedores (sin romper el contrato `Iterator[str]`)**.
   Añadir un parámetro opcional `usage_sink: MutableMapping[str, int] | None = None`
   a `stream()` de cada proveedor. Tras consumir el stream con éxito, el proveedor
   rellena `usage_sink` con `input_tokens`, `output_tokens` y `source`
   (`0` = reportado por el SDK, `1` = estimado por fallback). El proveedor sigue
   haciendo `yield` solo de `str`: el sink es un canal lateral, no cambia lo que
   se itera.
   - Anthropic: leer `stream_obj.get_final_message().usage`.
   - OpenAI: pasar `stream_options={"include_usage": True}` y leer `chunk.usage`
     del chunk final.

2. **Fallback best-effort cuando el SDK no reporta usage** (proxies/endpoints
   OpenAI-compatibles viejos): si al terminar no hay usage, estimar
   `input ≈ len(prompt)//4` y `output ≈ (chars emitidos)//4`, y marcar
   `source = 1` (estimado). Nunca se inventan números silenciosamente: la label
   `source` distingue medido de estimado en el dashboard.

3. **Métricas nuevas en `llm/client.py`** (mismo patrón lazy-init que
   `_get_llm_histogram`/`_histogram`, tolerante a `prometheus_client` ausente):
   - `llm_tokens_total` (Counter) — labels `model`, `provider`, `direction`
     (`input`|`output`), `source` (`reported`|`estimated`).
   - `llm_cost_usd_total` (Counter) — labels `model`, `provider`. Se incrementa
     desde un mapa estático `_PRICE_PER_MTOK: dict[str, tuple[float, float]]`
     (USD por millón de tokens, input/output). Modelo sin precio conocido →
     **se omite el coste** (no se adivina) y se loguea a DEBUG; los tokens sí se
     cuentan igual.

4. **Registro centralizado en el `finally` existente** de
   `stream_llm_response`: el cliente crea `usage: dict = {}`, lo pasa al proveedor,
   y en el mismo `finally` donde hoy observa la latencia, registra tokens y coste
   si el sink trae datos. Un único sitio de instrumentación; la firma pública de
   `stream_llm_response` **no cambia**.

**Qué NO se hace:**

- **No** se exponen los tokens en la respuesta del endpoint `/ask` ni en ningún
  DTO Pydantic — eso tocaría el contrato API↔web (§3.5) y es un RFC aparte si se
  quiere mostrar coste por respuesta en el frontend. Aquí el consumo es
  **interno** (Prometheus/Grafana), igual que la latencia hoy.
- **No** se añade presupuesto/budget enforcement (cortar requests al superar un
  umbral de coste). Esto es *medir antes de actuar*; el enforcement sería un RFC
  posterior una vez haya datos.
- **No** se refresca `AVAILABLE_MODELS` (hay IDs desactualizados:
  `claude-sonnet-4-5`, `gpt-3.5-turbo`, sin Opus). Se **flaggea** como ítem
  separado del backlog para no mezclar "medir coste" con "qué modelos ofrecemos".
- **No** se cambia el comportamiento ante consumo parcial: si el consumidor
  abandona el generador antes de agotarlo (`GeneratorExit`), el bloque de registro
  no corre y no se contabiliza ese request. Aceptable para un contador de
  observabilidad; se documenta.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Cada proveedor incrementa los counters directamente | Menos plumbing en el cliente | Duplica la lógica de métricas/coste en 2 sitios; rompe el patrón actual (las métricas viven en el cliente) | Inconsistente con la latencia, que ya se centraliza en el cliente |
| Yield de un objeto-sentinela final con el usage | No añade parámetros | Rompe el tipo `Iterator[str]`; obliga a cada consumidor a filtrar el sentinela | Viola el contrato público del cliente |
| Solo estimar con `len(prompt)//4` (sin tocar SDKs) | Cero cambios en proveedores | Ignora output; error grande; el dato real ya está disponible y gratis | Desperdicia precisión que el SDK ya entrega |
| Threadlocal/contextvar para devolver usage | Sin cambiar firmas | Estado implícito frágil con generadores y SSE concurrente | Más riesgo que un sink explícito por llamada |
| Coste vía API de billing del proveedor | Coste "oficial" | Asíncrono, con lag de horas/días; otra credencial; no sirve para alertar en vivo | Sobredimensionado; el mapa estático cubre el 95% |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Toca `llm/` (strict tras "Fase 6: Full strict typing") | Tipar estricto desde el inicio; `usage_sink: MutableMapping[str, int] \| None` |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno — sin cambios de schema | — |
| §3.4 Auto-marking tests | Ninguno — tests nuevos siguen convención de nombre | — |
| §3.5 Pydantic v2 DTOs | Ninguno — métricas internas, no contrato API | Se excluye exponer tokens en `/ask` (fuera de scope) |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. `llm/providers/anthropic_provider.py` — añadir `usage_sink` a `stream()`;
   tras el loop de `text_stream`, leer `get_final_message().usage` y poblar el
   sink. Fallback a estimación si no hay usage.
2. `llm/providers/openai_provider.py` — añadir `usage_sink`; pasar
   `stream_options={"include_usage": True}`; leer `chunk.usage` del chunk final;
   mismo fallback.
3. `llm/client.py` — counters `llm_tokens_total` y `llm_cost_usd_total` con
   lazy-init; mapa `_PRICE_PER_MTOK`; helper `_record_usage(model, provider, usage)`;
   crear `usage = {}`, pasarlo a `_stream(...)`, y registrar en el `finally`
   existente junto a la latencia.
4. `observability/` — (opcional, mismo PR) panel Grafana o regla de alerta de
   coste; si excede el scope, ítem de backlog.
5. `docs/IMPROVEMENT_BACKLOG.md` — ítem nuevo: **refrescar `AVAILABLE_MODELS`**
   (IDs desactualizados + guard anti-drift).
6. Tests: sink poblado desde un fake-stream Anthropic/OpenAI (reported), rama de
   estimación (source=estimated), modelo sin precio (tokens sí, coste no),
   `prometheus_client` ausente (no rompe), consumo parcial (no registra).

**Archivos de partida**: `llm/client.py`, `llm/providers/openai_provider.py`,
`llm/providers/anthropic_provider.py`, `observability/runtime_metrics.py`
(referencia de patrón de counters).
**Riesgo estimado**: bajo — aditivo; la firma pública `stream_llm_response` no
cambia y ningún consumidor existente se ve afectado.
**Tiempo estimado**: 0.5–1 día.

## Acceptance criteria

- [ ] `llm_tokens_total{direction="input|output",source="reported|estimated"}` se
      incrementa tras una respuesta de cada proveedor.
- [ ] `llm_cost_usd_total` refleja el coste de modelos con precio conocido y se
      omite (sin error) para modelos sin precio.
- [ ] El fallback de estimación marca `source="estimated"` y nunca falla la
      request por falta de usage.
- [ ] La firma pública de `stream_llm_response` no cambia; los consumidores de
      `/ask` siguen funcionando sin tocarse.
- [ ] Ausencia de `prometheus_client` no rompe el streaming (degradación limpia).
- [ ] `make lint && make typecheck && make test-unit` pasan en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<Comentarios del reviewer y security_triage durante la etapa agent:rfc-review.
Formato: `YYYY-MM-DDTHH:MMZ agent:reviewer — <comentario>`>
