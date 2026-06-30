---
rfc: 2026-06-30
title: Retrofit del pipeline PLACSP sobre el contrato Connector (cerrar la bifurcación de ingesta)
issue: pendiente — generado en sesión de arquitectura (revisión integral 2026-06-30); sin issue asociado aún
author: agent:architect
date: 2026-06-30
status: draft
---

## Contexto

ADR-009 introdujo el contrato `Connector` (`scraper/connectors/base.py`) y el
runner genérico `run_connector` (`scraper/connectors/base.py:138`) que concentra
la lógica probada del pipeline: cursor incremental (`ingestion_cursors`), upsert
idempotente con historial, persistencia de adjudicaciones, DLQ por aviso fallido,
resolución de empresas e invalidación de caché.

Hoy hay **3 conectores** sobre ese contrato —`ted.py`, `pscp.py`, `tacrc.py`—
pero el **PLACSP** (la fuente de producción, el grueso del volumen) sigue corriendo
por el camino legacy `scraper/pipeline.py` (descarga ZIP/ATOM → parseo CODICE/UBL →
filtro → upsert). ADR-009 lo marca explícitamente como **Pendiente**:

> *"Retrofit del pipeline PLACSP (bulk + ATOM) sobre el contrato Connector. El
> pipeline actual sigue siendo el camino de producción para PLACSP; el retrofit
> se hará con sus tests como red de seguridad."*

Esto es **dos caminos de ingesta coexistiendo**: el runner genérico (3 fuentes) y
el pipeline legacy (PLACSP). Es el patrón clásico que parece estable y diverge en
silencio: un fix de idempotencia, de manejo de DLQ, de avance de cursor o de
resolución de empresas se aplica en un camino y se olvida en el otro. El coste de
mantener la paridad crece con cada fuente nueva sobre `run_connector` mientras
PLACSP quede afuera, y la deriva no se detecta hasta que produce un bug de datos.

**Por qué ahora**: cerrar el retrofit *antes* de sumar las fuentes autonómicas
restantes (ADR-009 Fase 5) es estrictamente más barato — cada fuente nueva sobre
el camino viejo aleja la convergencia. Es deuda que se capitaliza.

## Decisión

Implementar un `PlacspConnector` (`scraper/connectors/placsp.py`) que adapte la
fuente PLACSP al contrato `Connector` (`source_id`, `fetch(cursor)`, `parse(raw)`)
y enrutar la producción a través de `run_connector`, **reutilizando** el parser
CODICE/UBL y el `bulk_downloader` existentes (con su protección anti ZIP-bomb,
backlog 2026-05-23 P2-5). El pipeline legacy `scraper/pipeline.py` se mantiene
como camino paralelo durante una **ventana de validación de paridad**, y se
deprecia solo cuando la paridad esté demostrada.

Estrategia de corte segura (los tests de PLACSP son la red, como pide ADR-009):

1. **Adaptar, no reescribir**: `PlacspConnector.fetch()` envuelve la descarga
   ZIP/ATOM actual; `parse()` envuelve el parser CODICE/UBL actual produciendo
   `ParsedTender`. La lógica de extracción no se toca — solo se la expone bajo el
   contrato. Esto contiene el riesgo: el código probado sigue siendo el mismo.
2. **Identidad**: las filas PLACSP **no** se prefijan (ADR-009 fue explícito: las
   PKs existentes no se migran; conservan el expediente crudo). El connector
   respeta esto — `source_id="placsp"` alimenta la columna `fuente`, no el `id_externo`.
3. **Validación de paridad**: correr ambos caminos sobre el mismo input bulk/ATOM
   en un entorno de prueba y diff de las filas resultantes (licitaciones +
   adjudicaciones + cursores + DLQ). Gate: **cero diferencias** salvo las
   esperadas y documentadas.
4. **Corte y deprecación**: una vez verde la paridad, `run_update`/scheduler
   enrutan PLACSP por `run_connector`; `scraper/pipeline.py` se marca DEPRECATED
   (no se borra de inmediato — se congela un ciclo por si hay que volver).

**Qué NO se hace:**

- **No** se reescribe el parser CODICE/UBL ni el `bulk_downloader` — se reutilizan.
- **No** se migran las PKs PLACSP a `placsp:...` (ADR-009 lo descartó por tocar
  todas las FKs/URLs).
- **No** se borra `scraper/pipeline.py` en este RFC — se deprecia tras paridad.
- **No** se cambia el contrato `Connector` para acomodar PLACSP; si PLACSP no
  encaja, eso es señal de un gap del contrato y se trata aparte (pero el diseño
  de ADR-009 se hizo justamente para que encaje).

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Dejar PLACSP en legacy indefinidamente | Cero riesgo de regresión hoy | La bifurcación diverge; cada fuente nueva encarece la paridad; el bug de deriva es invisible hasta que pega | Es la deuda que el RFC viene a cerrar |
| Reescribir PLACSP desde cero como connector | Código "limpio" | Tira a la basura un pipeline probado en producción; máximo riesgo de regresión | El parser/downloader son el activo; adaptarlos es más seguro |
| Corte directo sin ventana de paridad | Más rápido | Sin red de seguridad; PLACSP es la fuente crítica | Inaceptable para el grueso del volumen |
| Esperar a terminar las autonómicas y migrar todo junto | "Un solo esfuerzo" | Cada fuente nueva sobre legacy aleja la convergencia; el big-bang es más arriesgado | Capitaliza deuda en vez de pagarla |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | `scraper/` es strict; el connector nuevo nace strict | Tipar `PlacspConnector` desde el inicio |
| §3.2 Upsert idempotente | **Central** — el objetivo es que PLACSP use el upsert idempotente del runner | Gate de paridad valida idempotencia (re-run sin duplicar) |
| §3.3 Migraciones append-only | Ninguno — sin cambio de schema (la columna `fuente` ya existe, v37) | — |
| §3.4 Auto-marking tests | Ninguno — tests de paridad siguen naming | — |
| §3.5 Pydantic v2 DTOs | Ninguno — `ParsedTender` es interno, no contrato API | — |
| §3.6 HMAC/argon2 auth | Ninguno | — |
| §3.9 Plano único orquestación | El enrutado a `run_connector` respeta SCHEDULER_PLANE | Validar que el corte no duplica el run |

## Plan de implementación

1. `scraper/connectors/placsp.py` — `PlacspConnector` que envuelve descarga
   ZIP/ATOM + parser CODICE/UBL existentes, produciendo `RawNotice`/`ParsedTender`.
2. Test de paridad: ejecutar pipeline legacy vs `run_connector(PlacspConnector())`
   sobre un fixture bulk/ATOM fijo; diff de licitaciones/adjudicaciones/cursores/DLQ.
3. Enrutado: `scheduler/pipeline_runs.py` / `run_update` apuntan PLACSP a
   `run_connector` tras paridad verde.
4. `scraper/pipeline.py` — marcar DEPRECATED (docstring + no borrar todavía).
5. `docs/adr/ADR-009-framework-conectores-multifuente.md` — actualizar
   "Pendiente: retrofit PLACSP" → resuelto, con referencia a este RFC.

**Archivos de partida**: `scraper/connectors/base.py`,
`scraper/connectors/ted.py` (referencia de patrón fetch/parse),
`scraper/pipeline.py`, `scraper/bulk_downloader.py`,
`scheduler/pipeline_runs.py`, `docs/adr/ADR-009-framework-conectores-multifuente.md`.
**Riesgo estimado**: medio — toca el camino de datos de producción, mitigado por
la ventana de paridad y la reutilización (no reescritura) del parser/downloader.
**Tiempo estimado**: 2–4 días (mayoría en el harness de paridad).

## Acceptance criteria

- [ ] Existe `PlacspConnector` implementando el contrato `Connector` y reutilizando
      el parser/downloader actuales.
- [ ] El test de paridad demuestra **cero diferencias** (salvo las documentadas)
      entre legacy y `run_connector` sobre un fixture fijo.
- [ ] PLACSP en producción se enruta por `run_connector`; `scraper/pipeline.py`
      queda marcado DEPRECATED.
- [ ] Re-ejecutar el connector no duplica filas (idempotencia verificada, §3.2).
- [ ] ADR-009 actualizado: "Pendiente retrofit PLACSP" → resuelto.
- [ ] `make lint && make typecheck && make test-unit` (+ tests de scraper) en verde.

## Notas de review

<Comentarios del reviewer y security_triage durante la etapa agent:rfc-review.
Formato: `YYYY-MM-DDTHH:MMZ agent:reviewer — <comentario>`>
