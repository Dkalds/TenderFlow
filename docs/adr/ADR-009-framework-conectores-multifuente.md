---
id: ADR-009
title: "Framework de conectores multi-fuente y namespacing de id_externo"
status: accepted
date: 2026-06-11
deciders: "Daniel Kalitovics"
tags: [adr]
---

# ADR-009: Framework de conectores multi-fuente y namespacing de id_externo

**Status:** Accepted
**Date:** 2026-06-11
**Deciders:** Daniel Kalitovics

## Context

La plataforma ingiere una única fuente (PLACSP: ZIPs bulk + feed ATOM). Para el
análisis de competencia completo se necesitan más fuentes — TED (contratos
sobre umbrales armonizados UE), plataformas autonómicas (PSCP Catalunya,
Euskadi…) — y cada una tiene su propio esquema de identificadores. Dos
decisiones bloqueantes:

1. **Identidad**: `licitaciones.id_externo` es PK y hoy contiene el expediente
   PLACSP crudo. Dos fuentes pueden colisionar en el mismo identificador.
2. **Contrato de ingesta**: el pipeline PLACSP (descarga → parseo → filtro →
   upsert con historial → DLQ → cursores) está cableado a su fuente; añadir
   una fuente nueva no debe duplicar esa lógica.

## Decision

1. **Namespacing prospectivo de `id_externo`**: las fuentes nuevas insertan
   `"{source_id}:{id_natural}"` (p. ej. `ted:371218-2026`). Las filas PLACSP
   existentes **no se migran**: conservan su expediente crudo. Se añade la
   columna `licitaciones.fuente` (v37, default `'placsp'`, backfill incluido)
   como discriminador explícito para filtros y métricas de cobertura.
2. **Contrato `Connector`** (`scraper/connectors/base.py`): cada fuente
   implementa `source_id`, `fetch(cursor) → iterator de avisos crudos` y
   `parse(raw) → ParsedTender (Licitacion + Adjudicaciones)`. Un runner
   genérico (`run_connector`) aporta lo común: cursor incremental
   (`ingestion_cursors`), upsert idempotente con historial, persistencia de
   adjudicaciones, DLQ por aviso fallido, resolución de empresas (v35) e
   invalidación de caché.

## Rationale

- Migrar las PKs existentes a `placsp:...` tocaría todas las FKs
  (adjudicaciones, history, FTS, tecnologia_score), las URLs de la API y los
  enlaces guardados por usuarios — alto riesgo sin beneficio: el prefijo solo
  es necesario para garantizar unicidad de las fuentes *nuevas*.
- La columna `fuente` da la semántica ("de dónde vino esto") sin depender de
  parsear el prefijo del id.
- El runner genérico concentra la lógica probada del pipeline (idempotencia,
  DLQ, cursores) — añadir una fuente pasa de "duplicar el pipeline" a
  "implementar fetch + parse".

## Consequences

- **Positivo:** TED entra con ~200 líneas (fetch + mapeo eForms). Las
  autonómicas (Fase 5) son un conector cada una.
- **Negativo:** inconsistencia estética: filas PLACSP sin prefijo, resto con
  él. Mitigada por la columna `fuente`.
- **Resuelto (Fase 5.2, RFC 20260611-1):** dedupe cross-fuente — un contrato
  grande que aparece en PLACSP *y* TED se marca de forma reversible en
  `licitaciones_duplicados` (`services/dedupe.py`); las consultas analíticas lo
  excluyen vía `exclude_duplicados_sql()`. La clave débil de matching es
  órgano normalizado + expediente nacional + CPV-4. Un guardrail de test
  (`tests/test_dedup_guardrail.py`) falla en CI si una consulta analítica nueva
  sobre `licitaciones`/`adjudicaciones` omite el filtro.
- **Resuelto (F2, activado 2026-07-11):** retrofit del pipeline PLACSP (bulk +
  ATOM) sobre el contrato `Connector`. `PlacspAtomConnector` /
  `PlacspBulkConnector` (`scraper/connectors/placsp.py`) reutilizan el parser
  CODICE y el fallback ML del pipeline; `PLACSP_CONNECTOR_ENABLED=True` enruta
  producción por `run_connector`. Validación previa al flip: 16 tests de
  contrato/paridad + paridad sobre datos reales del feed ATOM (ventana de 3
  días, 6.320 entries → 196 licitaciones y 166 adjudicaciones idénticas campo
  a campo entre legacy y connector). Diferencias documentadas del flip:
  (1) el cursor diario pasa de la clave `place_live_atom` a `placsp`, con
  fallback one-time de lectura del cursor legacy; (2) `licitaciones_history.source`
  y la `fuente` de `extracciones` del carril diario pasan a `placsp`;
  (3) el camino connector ejecuta además `services/dedupe.py` post-ingesta
  (el legacy no lo hacía). `scraper/pipeline.py` queda DEPRECATED como camino
  de rollback; el carril **backfill** aún delega en él (sin camino connector).

## Alternatives Considered

| Alternative | Reason rejected |
|-------------|----------------|
| Migrar todas las PKs a `fuente:id` | Toca todas las FKs y rompe URLs/integraciones; riesgo desproporcionado |
| PK compuesta (fuente, id_externo) | Cambio de esquema invasivo en SQLite (recrear tablas + FKs) |
| Tabla por fuente | Fragmenta queries y analytics; el modelo canónico único es el activo |
