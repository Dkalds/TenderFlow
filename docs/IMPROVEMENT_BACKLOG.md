# Improvement Backlog

Lista viva de mejoras conocidas, priorizadas. **Diseñada para que un agente pueda elegir un ítem y trabajarlo sin pedir contexto extra al usuario.**

## Convenciones

- **Prioridad**: P0 (urgente / bloquea) · P1 (alta) · P2 (media) · P3 (nice-to-have).
- **Riesgo**: bajo (cambio aislado) · medio (afecta varios módulos) · alto (toca core / migra schema / cambia contrato).
- Si añadís un ítem nuevo, copiá la plantilla del final.
- Al cerrarlo, no lo dejes tachado aquí: **movélo entero a la sección _Cerrados_** del final con la fecha y el commit/PR que lo resolvió. Las secciones P1/P2/P3 contienen **solo ítems abiertos**.

---

## P1 — Alta

### [P1] Plan de migración de persistencia pre-cocido con disparador binario
- **Área:** db/, observability, docs/adr
- **Problema:** [[ADR-004-sqlite-turso-vs-postgres|ADR-004]] reconoce que la premisa "single writer" de SQLite **ya no se cumple** (scraper + scheduler + API + dashboard escriben concurrentemente, y [[ADR-009-framework-conectores-multifuente|ADR-009]] sumó 3 conectores). Hay tripwires que *detectan* el riesgo pero la *decisión* de migración sigue diferida: cuando salte el tripwire, habrá que diseñar la migración bajo presión de incidente. Falta el plan en frío.
- **Acceptance criteria:**
  - Existe ADR-015 con **un** destino de persistencia decidido y justificado (no una disyuntiva abierta).
  - Spike en branch que levanta el destino, corre `alembic upgrade head` y pasa un test de paridad de búsqueda FTS5↔reemplazo (`pg_trgm`).
  - Runbook `docs/runbooks/migracion-persistencia.md` con corte, gates de paridad y rollback.
  - La alerta del tripwire enlaza al runbook; el RFC declara el umbral que escala la **ejecución** a P0.
- **Files de partida:** [docs/adr/[[ADR-004-sqlite-turso-vs-postgres|ADR-004]]-sqlite-turso-vs-postgres.md](../docs/adr/[[ADR-004-sqlite-turso-vs-postgres|ADR-004]]-sqlite-turso-vs-postgres.md), [docs/runbooks/persistence-tripwires.md](../docs/runbooks/persistence-tripwires.md), [observability/alert_rules.yml](../observability/alert_rules.yml), [db/connection.py](../db/connection.py)
- **RFC:** [2026-06-30-rfc-plan-migracion-persistencia-pre-cocido.md](rfc/2026-06-30-rfc-plan-migracion-persistencia-pre-cocido.md)
- **Riesgo:** bajo en preparación (docs + spike aislado); de-riesga una ejecución futura de riesgo alto. **La ejecución escala a P0 al dispararse el tripwire** (`sqlite_busy_errors_total` >10/h o `db_concurrent_writers` >3 sostenido).

### [P1] Retrofit del pipeline PLACSP sobre el contrato Connector
- **Área:** scraper/ (connectors + pipeline), scheduler
- **Problema:** Hay dos caminos de ingesta coexistiendo: `run_connector` (3 fuentes: ted/pscp/tacrc) y el pipeline legacy `scraper/pipeline.py` (PLACSP, la fuente de producción). [[ADR-009-framework-conectores-multifuente|ADR-009]] marca el retrofit como Pendiente. La bifurcación diverge en silencio (un fix de idempotencia/DLQ/cursor aplicado en un camino y no en el otro) y encarece con cada fuente nueva. Cerrarlo antes de las autonómicas restantes es más barato.
- **Acceptance criteria:**
  - Existe `PlacspConnector` implementando el contrato `Connector` y **reutilizando** el parser CODICE/UBL y el `bulk_downloader` actuales (no reescritura).
  - Test de paridad con **cero diferencias** (salvo documentadas) entre legacy y `run_connector` sobre un fixture fijo; idempotencia verificada.
  - PLACSP en producción se enruta por `run_connector`; `scraper/pipeline.py` queda DEPRECATED; [[ADR-009-framework-conectores-multifuente|ADR-009]] actualizado.
- **Files de partida:** [scraper/connectors/base.py](../scraper/connectors/base.py), [scraper/pipeline.py](../scraper/pipeline.py), [scraper/bulk_downloader.py](../scraper/bulk_downloader.py), [docs/adr/[[ADR-009-framework-conectores-multifuente|ADR-009]]-framework-conectores-multifuente.md](../docs/adr/[[ADR-009-framework-conectores-multifuente|ADR-009]]-framework-conectores-multifuente.md)
- **RFC:** [2026-06-30-rfc-retrofit-pipeline-placsp-connector.md](rfc/2026-06-30-rfc-retrofit-pipeline-placsp-connector.md)
- **Riesgo:** medio — toca el camino de datos de producción; mitigado por ventana de paridad y reutilización (no reescritura) del parser/downloader.

### [P1] LLM como dependencia gestionada (presupuesto + circuit-breaker + fallback + eval RAG)
- **Área:** llm/, api/routes/ask.py, observability
- **Problema:** `/ask` es ahora un camino de producción con proveedor externo de pago (NVIDIA NIM/DeepSeek, commit `d6619f8`). El RFC de tokens (`implemented`) cerró la *medición* y dejó el *enforcement* para "un RFC posterior". Falta: presupuesto/circuit-breaker de gasto, fallback degradado si el proveedor cae, y eval de RAG (sin eval set las regresiones de calidad son invisibles a CI). Este es ese RFC posterior.
- **Acceptance criteria:**
  - Con presupuesto superado y `LLM_BUDGET_MODE=enforce`, `/ask` responde 429/503 sin llamar al proveedor; `llm_budget_exceeded_total` sube. Modo `monitor` solo alerta.
  - Ante fallo del proveedor o breaker abierto, `/ask` degrada a documentos del RAG sin síntesis (`degraded` en el stream); el SSE no rompe y el DTO no cambia (§3.5).
  - Eval de **recuperación** determinista en CI (sin LLM real) que falla si se rompe el contexto recuperado.
- **Files de partida:** [api/routes/ask.py](../api/routes/ask.py), [llm/client.py](../llm/client.py), [config/settings.py](../config/settings.py), [docs/adr/[[ADR-006-etag-pdf-export-ratelimit-redis|ADR-006]]-etag-pdf-export-ratelimit-redis.md](../docs/adr/[[ADR-006-etag-pdf-export-ratelimit-redis|ADR-006]]-etag-pdf-export-ratelimit-redis.md)
- **RFC:** [2026-06-30-rfc-llm-dependencia-gestionada.md](rfc/2026-06-30-rfc-llm-dependencia-gestionada.md)
- **Riesgo:** medio — toca un endpoint de producción; mitigado por `LLM_BUDGET_MODE=monitor` como default (medir antes de cortar) y contrato API intacto. **Construye sobre** el RFC de observabilidad de tokens (P2, abajo).

### [P1] Validación de precisión del dedupe cross-fuente + linaje de datos
- **Área:** services/ (dedupe), tests, observability
- **Problema:** Con multi-fuente, el riesgo se desplaza de "¿extrajimos el campo?" a "¿es correcto el dato fusionado?". El guardrail actual (`test_dedup_guardrail.py`) valida que las queries *filtren* duplicados, **no que el matching acierte**. Un falso positivo del dedupe (clave débil órgano+expediente+CPV-4) **borra una licitación real** del análisis de competencia —el producto— sin detección. La heurística no tiene medición de precision/recall.
- **Acceptance criteria:**
  - Golden set `tests/fixtures/dedupe_golden.jsonl` etiquetado a mano con casos borde.
  - `tests/test_dedupe_quality.py` mide precision/recall y falla en CI si la precision baja del umbral (no puede bajar sin justificación en review).
  - `services/dedupe.py` registra el criterio de cada match (linaje auditable); `dedupe_match_rate` con alerta de desviación.
- **Files de partida:** [services/dedupe.py](../services/dedupe.py), [tests/test_dedup_guardrail.py](../tests/test_dedup_guardrail.py), [docs/adr/[[ADR-009-framework-conectores-multifuente|ADR-009]]-framework-conectores-multifuente.md](../docs/adr/[[ADR-009-framework-conectores-multifuente|ADR-009]]-framework-conectores-multifuente.md)
- **RFC:** [2026-06-30-rfc-validacion-dedupe-linaje-datos.md](rfc/2026-06-30-rfc-validacion-dedupe-linaje-datos.md)
- **Riesgo:** bajo — aditivo (tests + métricas + linaje); no cambia el algoritmo de matching (primero mide). El único punto sensible es una eventual migración de schema, gateada por OK humano.

---

## P2 — Media

### [P2] Modo degradado documentado y testeado ante caída de dependencias opcionales
- **Área:** api/routes/health.py, observability, scheduler, config
- **Problema:** Se ha reducido la superficie operativa (FAISS eliminado en Fase 3, dramatiq en Fase 4, Redis desacoplado en Fase 5), pero aún falta un contrato explícito y testeado de qué sigue funcionando cuando cae Turso, el modelo ML o Redis en producción. Síntoma ya conocido: `/health` devuelve 503 en local cuando `REDIS_URL` está seteado pero Redis no corre.
- **Acceptance criteria:**
  - Documento (`docs/runbooks/degraded-mode.md`) que enumera cada dependencia opcional (Redis/Upstash, Turso réplica, modelo ML stale) y qué funcionalidad sobrevive / degrada / cae.
  - `/health` (o `/ready`) distingue **degradado** de **no disponible** sin devolver 503 cuando solo cayó algo opcional.
  - Al menos un test por dependencia opcional que verifique que el camino crítico sigue verde.
- **Files de partida:** [api/routes/health.py](../api/routes/health.py), [scheduler/healthcheck.py](../scheduler/healthcheck.py)
- **Riesgo:** bajo — mayormente aditivo.

### [P2] Cobertura de tests del frontend en flujos críticos
- **Área:** web/ (tests vitest)
- **Problema:** El frontend tiene thresholds reales 68/63/68/70 (vitest.config.ts) con 82 test files. Los flujos críticos de valor (filtros nuqs URL↔estado, watchlist, streaming `/ask`) no tienen cobertura. Una regresión en esos flujos pasa CI en verde.
- **Acceptance criteria:**
  - Tests para los 3 flujos: filtros nuqs (`web/src/lib/filters.ts`), watchlist (`use-watchlist-items`), streaming SSE de `/ask` (`ask-stream.ts` / `use-ask.ts`). `use-ask` cubierto al 100% en commit 52ad203; resta `ask-stream.ts`.
  - Thresholds de `vitest.config.ts` subidos anti-regresión (actualmente 68/63/68/70 tras subida de Fase 9 de cobertura 2026-07-04).
  - Tests no dependen de la API real (mock del cliente OpenAPI generado).
- **Files de partida:** [web/vitest.config.ts](../web/vitest.config.ts), [web/src/lib/filters.ts](../web/src/lib/filters.ts), [web/src/lib/ask-stream.ts](../web/src/lib/ask-stream.ts)
- **Riesgo:** bajo — solo añade tests.

---

## P3 — Nice to have

*(sin ítems abiertos)*

---

## Cerrados

- [2026-06-30] **P2: Observabilidad de tokens y coste en el cliente LLM** — `llm/client.py` instrumenta `llm_tokens_total{model,provider,direction,source}` y `llm_cost_usd_total{model,provider}` con lazy-init tolerante a `prometheus_client` ausente, mapa estático `_PRICE_PER_MTOK` (modelo sin precio → solo tokens, coste omitido sin error) y `_record_usage()` centralizado en el `finally` de `stream_llm_response` (firma pública intacta). Ambos providers rellenan un `usage_sink` lateral: Anthropic vía `get_final_message().usage`, OpenAI vía `stream_options={"include_usage":True}`, con fallback de estimación (`source=estimated`) cuando el SDK no reporta. Tests en `tests/test_unit_llm_usage.py` (9): counters reported/estimated, modelo sin precio, dict vacío no-op, sin prometheus, sink poblado en ambos providers, **estimación a nivel provider** y **consumo parcial no contabiliza** (los 2 últimos añadidos para cerrar el RFC). `mypy .` verde (418 files). RFC `2026-06-17` → implemented.

- [2026-06-10] **P2: Fix `test_expired_key_returns_401` + bug real de expiración en `require_any_auth`** — La causa raíz no era infra de test sino un **bug de producción**: `api/routes/dual_auth.py::require_any_auth` (usado por `/api/v1/licitaciones` y otros endpoints con dual auth sesión/API-key) llamaba a `lookup_active_key` pero **nunca comprobaba `expires_at`**, a diferencia de `api/auth.py::require_api_key`. Una API key expirada seguía siendo válida en estos endpoints. Fix: añadido el mismo check `record.expires_at and now_utc_iso() > record.expires_at` en `dual_auth.py`. Además, `tests/test_api.py::test_expired_key_returns_401` ahora llama a `close_pool()` tras el `UPDATE` para evitar lecturas de conexión thread-local obsoletas. `pytest tests/test_api.py` 24/24 verde.
- [2026-06-10] **P2: Cobertura de tests del frontend — `useSearchHistory` y `SearchAutocomplete`** — 2 archivos nuevos: `web/src/lib/__tests__/search-history.test.ts` (dedupe, cap de 10, rechazo de términos < 2 chars, trim, persistencia en `localStorage`) y `web/src/components/__tests__/search-autocomplete.test.tsx` (navegación con teclado ArrowUp/Down sin wrap, Enter sobre item activo vs. valor actual, Escape, aria-expanded/aria-activedescendant, selección por click). Suite 245 → **268** tests (15 → 17 archivos). Thresholds de `vitest.config.ts` subidos 30/25→32/27 (statements/lines 32, branches/functions 27).
- [2026-06-09] **Deps: cerradas las 3 alertas moderate de Dependabot** — `web/package.json`: `overrides` forzando `postcss: ^8.5.10` (resuelto 8.5.15) → `npm audit` 0 vulns, `next build` OK (no había Next estable con el fix). `requirements-dev.txt`: `pytest>=8.0.0,<9` → `>=9.0.3,<10` (CVE-2025-71176; compatible con pytest-cov/benchmark, suite verificada). Nota operacional: el `.venv` local tenía `starlette 0.52.1` stale — el manifest ya pinea `1.2.0` parcheado; basta reinstalar (`pip install -r requirements.txt`). Audit-gate en CI queda en el ítem de CI frontend.
- [2026-06-09] **P1: CI frontend job** — `.github/workflows/ci.yml`: nuevo job `frontend` con `defaults.run.working-directory: web`, Node 22, caché npm por `web/package-lock.json`. Pasos: `npm ci` → `typecheck` → `lint` → `test` (vitest) → `build` (next build). Corre en paralelo con los jobs de Python.
- [2026-06-09] **Lint: deuda de frontend completamente limpia (160→0 warnings, 0 errores)** — jsx-a11y completo (todos los grupos, −112), exhaustive-deps (wrapping `?? []` en `useMemo`, `TIPO_CONTRATO_LABEL` extraído, −36), React Compiler (`set-state-in-effect`/`purity`/`immutability`/`incompatible-library`, −6, eslint-disable documentado). Vuelta final: 48 `no-unused-vars`/`no-explicit-any` eliminados en 22 archivos (imports muertos, useMemo dead code, args renombrados a `_`). `no-explicit-any` y `no-unused-vars` endurecidos de `warn` a `error`. `eslint src/` 0, `tsc --noEmit` 0.
- [2026-06-09] **Fix filtros barra superior (nuqs)** — `web/src/lib/filters.ts`: `shallow: false → true` + `history: "push" → "replace"`. Ningún Server Component consume los filtros (todas las páginas son "use client" + React Query), así que `shallow:false` solo añadía un round-trip al servidor por cambio → lag/carrera que obligaba a re-seleccionar/resetear. Ahora aplican a la primera. `tsc` 0, filters test 17.
- [2026-06-09] **Fix active-learning campos backend** — `web/src/app/(dashboard)/active-learning/page.tsx`: alineados los nombres con `/api/v1/feedback/queue` (`expediente`→`id_externo`, `proba/probability`→`confidence`). Arregla el warning de `key`, el envío de feedback (antes mandaba `expediente: undefined`) y la barra de probabilidad.
- [2026-06-09] **`.env.example` completado** — añadidos `WEBHOOK_SIGNING_KEY`, `TOTP_ENCRYPTION_KEY` (+ comando Fernet), `CORS_ALLOWED_ORIGINS`, `METRICS_ALLOWED_IPS`, OTEL, alertas SMTP, `DRAMATIQ_BROKER_URL`, `DB_POOL_*`, y nota apuntando a `config/settings.py` para el resto de knobs.
- [2026-06-09] **kpi_precompute N+1 → executemany** — `scheduler/kpi_precompute.py::_persist_snapshots` usa `executemany` (+ early-return vacío); 2 tests nuevos (batch de 5 filas, lista vacía) en `test_kpi_precompute.py`.
- [2026-06-09] **next.config puerto API 8081→8080** — fallback del rewrite `API_BASE_URL` corregido; `make api` + `npm run dev` sin vars extra ya sirve datos.
- [2026-06-09] **CSP Report-Only** — `next.config.ts`: header `Content-Security-Policy-Report-Only` con `frame-ancestors/object-src/base-uri/form-action` estrictos + `report-uri /api/v1/security/csp-report` (fase 1: medir antes de enforce).
- [2026-06-09] **`any` eliminados en frontend** — `mi-watchlist` (`unknown`), formatters de recharts tipados en `chart-formatters.ts` y usados sin cast (3 sitios en `pipeline-alertas`), `force-graph` d3 sin `as any` (null-guard + `selectAll` con generics). `tsc` 0, lint 0 errores, vitest 241.
- [2026-06-09] **Lint a11y (progresivo)** — desactivada la regla deprecada `jsx-a11y/label-has-for` (−29); `aria-label` en `global-filter-bar` y `filters-sidebar` (−4). Warnings 156→123. +4 tests en `chart-formatters.test.ts` (suite 245).
- [2026-06-08] **P1: `lead_time_medio` en detalle de órgano** — `services/analytics/organo_detail.py`: nuevo `_lead_time_median()` calcula la mediana de `(fecha_adjudicacion − fecha_publicacion)` en días (solo positivos) sobre las adjudicaciones del órgano; antes devolvía siempre `None`. Tests en `tests/test_analytics_organos.py`.
- [2026-06-08] **P1: Caché de DataFrames en analytics** — `services/_data_cache.py::SignalAwareCache` (TTL 60s + invalidación por `shared.cache_signal`) aplicada a `load_stats_dataframe()` y al caso sin filtros de `load_raw_adjudicaciones()`; `clear_stats_cache()`/`clear_raw_adj_cache()` + fixture autouse en `tests/conftest.py`. Evita N relecturas de SQLite por request. Tests en `tests/test_data_cache.py`.
- [2026-06-08] **P2: Tests unitarios de analytics** — `tests/test_analytics_organos.py` (10 tests): `get_organos`, `get_organo_detail` (lead_time, estado_desc, url, paridad) y `get_overview` con DataFrames sintéticos + caso vacío. Fix de tipado: `adj_lookup: dict[str, dict[str, Any]]` en `organo_detail.py`.
- [2026-06-08] **P2: Paridad Streamlit ↔ Next.js (Sheet órgano)** — `TopScored` + card del Sheet exponen `url` (título clickeable), `estado_desc` (legible), `tipo_proyecto`, `tipo_contrato_desc`, `cpv_desc`. Backend `organo_detail.py` + `web/src/app/(dashboard)/organos/page.tsx`.
- [2026-06-08] **P3: Keyboard nav en Sankey** — `web/src/components/charts/sankey-chart.tsx`: `aria-label` por nodo (label + origen/destino + flujo), navegación con flechas/Home/End entre nodos, TODO eliminado.
- [2026-06-08] **P3: Política de skips documentada** — `docs/testing.md`: sección "Skips condicionales" (pandera/dramatiq/puerto); `fail_under` corregido 51 → 70.
- [2026-06-08] **Auditorías (sin cambio de código)** — `# noqa: S608` (4 inline) confirmadas seguras y ya documentadas en `pyproject.toml`; fachada `db.database` ya documentada (docstring + AGENT_PLAYBOOK); `pandas-stubs` ya declarado en `requirements-dev.txt`.
- [2026-06-08] **mypy strict drift corregido** — 3 errores (por upgrade de `pandas-stubs` 2.3.3): `tecnologias.py` `.apply(include_groups=False)` → `is_adj.groupby(...).mean().mul(100)` (vectorizado, equivalencia verificada); `clusters.py` `int(cid)` → `int(cast("SupportsInt", cid))`; `rate_limit_redis.py` eliminado `# type: ignore[assignment]` no usado. `mypy services/` limpio.
- [2026-06-08] **ESLint frontend desbloqueado** — `web/eslint.config.mjs`: eliminada la doble registración del plugin `jsx-a11y` (`ConfigError: Cannot redefine plugin`); `src/generated/**` ignorado; 2 interfaces vacías shadcn (`textarea.tsx`, `dropdown-menu.tsx`) → alias de tipo. Reglas con deuda heredada (`exhaustive-deps`, `jsx-a11y` recommended, React Compiler) en `warn` para limpieza progresiva. `npm run lint` pasa de crash a exit 0.
- [2026-05-23] **P0-1: SSE columns fix** — `api/routes/stream.py`: `created_at`/`updated_at` (inexistentes en `licitaciones`) reemplazados por `fecha_extraccion`/`fecha_actualizacion_fuente`.
- [2026-05-23] **P0-2/P0-3: Async webhook ping + await run_db** — `api/routes/webhooks.py`: `requests.post` síncrono envuelto con `asyncio.to_thread()`; `_repo.create()` envuelto con `await run_db()`.
- [2026-05-23] **P1-1: Import Prometheus top-level** — `api/app.py`: eliminado `try/except ImportError` de `prometheus_fastapi_instrumentator` (hard dep en `pyproject.toml`); import movido al bloque top-level.
- [2026-05-23] **P1-2: 4 índices BD faltantes (v21)** — `db/alembic/versions/v21_missing_indexes.py`: `idx_lic_tecnologia`, `idx_lic_cursor`, `idx_lic_importe`, `idx_domain_events_actor`.
- [2026-05-23] **P1-3: Trivy SARIF separado en CI** — `.github/workflows/ci.yml`: step de Trivy dividido en tabla (exit-code 1) + SARIF separado.
- [2026-05-23] **P2-1: Rate limiting CSP report** — `api/routes/security.py`: 10 req/min por IP en `/csp-report`.
- [2026-05-23] **P2-2: DASHBOARD_PASSWORD SecretStr** — `config/settings.py`: `DASHBOARD_PASSWORD: SecretStr`; 6 call sites actualizados con `.get_secret_value()`.
- [2026-05-23] **P2-3: Health check Redis + disk** — `api/routes/health.py`: `_check_redis()` (ping 2s timeout), `_check_disk()` (threshold 500 MB); `/ready` devuelve 503 si degraded.
- [2026-05-23] **P2-4: `db.database` fachada pura** — Eliminadas copias locales de `safe_pragma` y `connect_read`; re-exporta desde `db.connection`. `test_turso_backend_compat.py` actualizado para patchear `db.connection` directamente.
- [2026-05-23] **P2-5: ZIP bomb protection** — `scraper/bulk_downloader.py`: límite 10 000 entries, ratio compresión > 100:1 → skip, lectura streaming con contador bytes.
- [2026-05-23] **P3-1: Reemplazar print() por structlog** — `scheduler/kpi_precompute.py`, `scheduler/aggregates_precompute.py`: `print()` → `log.info/warning/error`.
- [2026-05-23] **P3-3: Unificar rango sentence-transformers** — `pyproject.toml`: extras `ml` y `ml-embeddings` unificados a `>=2.2.0,<4`.
- [2026-05-23] **P3-4: AGENTS.md invariante #1 corregido** — `config/*` y `shared/*` marcados como "pending strict"; `db.database`, `db.users`, `dashboard.bootstrap` son los módulos strict confirmados.
- [2026-05-23] **P3-5: 4 test files nuevos (33 tests)** — `tests/test_auth.py` (11), `tests/test_db_connection.py` (9), `tests/test_admin.py` (6), `tests/test_tracing.py` (7). Bugs de test corregidos: reload() → monkeypatch.setattr en settings instance; columna `active` → `is_active`; `_DB_PATH_OVERRIDE` para is_turso_backend; `revoke_api_key` recibe `key_id: int`.
- [2026-05-23] **Coverage gate en CI** — Fase 3: `--cov-fail-under=55` en `pyproject.toml` sección `[tool.coverage.report]`. Coverage target subido de 51 a 55.
- [2026-05-23] **`.editorconfig` compartido** — Fase 8: creado `.editorconfig` con UTF-8, LF, trim trailing whitespace, indent 2 para yaml/json/md, 4 para Python.
- [2026-05-23] **`docs/testing.md`: guía de tests** — Fase 8: creado `docs/testing.md` con markers, naming, fixtures, cómo correr subsets.
- [2026-05-23] **`docs/api-design.md`: convenciones REST** — Fase 8: creado `docs/api-design.md` con nomenclatura, errores, paginación, scopes.
- [2026-05-23] **`CONTRIBUTING.md`: convenciones de PR/commit/branch** — Fase 8: creado `CONTRIBUTING.md` con branch naming, conventional commits, PR checklist, pre-commit.
- [2026-05-23] **Seguridad P0: scopes en endpoints sin protección** — Fase 1: `require_scope("admin")` en models activate, `require_scope("webhooks:read")` en 3 GET de webhooks, whitelist en `_distinct()`, sanitización de errores en exports.
- [2026-05-23] **ML foundation: validación de datos de entrenamiento** — Fase 2: `validate_training_data()` en `ml_pipeline.py`, feature store conectado en `predict_proba()`, warning de doble calibración.
- [2026-05-23] **Tests: 4 nuevos test files (26 tests)** — Fase 3: `test_threshold_tuning.py` (8), `test_model_registry.py` (7), `test_feature_store.py` (5), `test_drift_report.py` (6).
- [2026-05-23] **ML improvements: tuning, CV, CPV tokens, drift KS** — Fase 4: `RandomizedSearchCV` con `ML_TUNE_ON_TRAIN`, `StratifiedKFold`/`RepeatedStratifiedKFold`, CPV2/CPV4 en `_augment_text()`, `_prediction_drift()` KS test.
- [2026-05-23] **Code quality: silent exceptions → logged** — Fase 5: 18 `except Exception: pass` en `db/migrations.py` ahora logean `log.warning()`. `python_version` corregido a `"3.11"`.
- [2026-05-23] **DevOps: Docker hardening + Makefile** — Fase 6: Trivy `exit-code: "1"`, Docker compose security (security_opt, cap_drop, read_only, tmpfs, Redis ports ocultos, Grafana password obligatoria), Alembic `target_metadata` conectado, 4 targets nuevos en Makefile.
- [2026-05-23] **Advanced ML: embeddings + multi-metric promotion** — Fase 7: `SentenceEmbeddingTransformer` + `ML_USE_EMBEDDINGS`, gate de promoción multi-métrica (F1 + PR-AUC + Brier) en `concept_drift.py`.
- [2026-05-23] **A1: seed_negatives Turso compat** — Bug fix: `seed_negatives` en `scraper/ml_training.py` migrado de `sqlite3.connect(db_file)` a `db.database.connect()`, corrigiendo incompatibilidad con Turso.
- [2026-05-23] **B1: Índices de rendimiento v32** — Migración 32: 4 índices (`idx_lic_tecnologia`, `idx_lic_ml_proba`, `idx_adj_nombre_importe`, `idx_adj_ccaa_nombre`) con rollback.
- [2026-05-23] **B2: executemany en precompute_ml_proba** — Reemplazo de N+1 UPDATEs individuales por `executemany` en `scraper/ml_training.py`.
- [2026-05-23] **B3: LEFT JOIN en active learning queries** — `get_unlabelled_candidates` y `get_unlabelled_random` reescritos de `NOT IN (SELECT …)` a `LEFT JOIN … IS NULL`.
- [2026-05-23] **B4: SUBSTR en _compute_clusters** — `SUBSTR(descripcion, 1, 500)` para limitar memoria en clustering.
- [2026-05-23] **C1-C5: 5 test files de seguridad (63 tests)** — `test_middleware.py` (17), `test_gdpr.py` (13), `test_totp.py` (12), `test_webhooks.py` (10), `test_partners.py` (11).
- [2026-05-23] **C6: Rate limiting diferenciado por endpoint** — Endpoints pesados (exports, ML inference, semántica) tienen límite inferior configurable en `_HEAVY_ENDPOINT_LIMITS` (10-30 req/min vs 120 default).
- [2026-05-23] **C7: SHA256 verification en TechnologyClassifier.load()** — Verificación de integridad SHA-256 del sidecar `.sha256` al cargar el modelo, alineando con `ml_classifier.py`.
- [2026-05-23] **D1: predict_batch con _augment_text** — `predict_batch` ahora acepta `cpvs`/`importes` opcionales y aplica `_augment_text` a cada texto, corrigiendo predicciones silenciosamente peores que `predict()`.
- [2026-05-23] **D2: Alerta de modelo ML obsoleto** — `check_ml_model_staleness()` en `observability/alerts.py`: alerta WARN si el clasificador SAP tiene > 30 días.
- [2026-05-23] **D3: Prometheus histogram para latencia ML** — `ml_inference_duration_seconds` en `observability/runtime_metrics.py`, instrumentado en `predict()` y `predict_batch()` de `SAPClassifier`.
- [2026-05-23] **Strict typing en `dashboard/`** — Bloque 10a/10b: `dashboard.cache` y `dashboard.data_loader` eliminados del override `ignore_errors`. `dashboard/router.py` y `dashboard/filters/` confirmados ya tipados.
- [2026-05-23] **Bloque 9: SQL S608 eliminado** — Todas las `# noqa: S608` del proyecto principal eliminadas (11 ocurrencias en 9 ficheros). Reemplazadas con concatenación de strings.
- [2026-05-23] **Bloque 8: Infraestructura staging** — `docker-compose.override.yml`, `docker-compose.staging.yml`, `ENV` Literal ampliado a `"dev" | "staging" | "prod"`, `.github/workflows/deploy-staging.yml`.
- [2026-05-23] **Bloque 6: ML features activadas + endpoint /ask** — `ML_TECH_ENABLED=True`, `ML_TECH_AUTO_RETRAIN=True`, endpoint `POST /api/v1/ask` (RAG + SSE streaming), `GET /api/v1/ask/models`.
- [2026-05-23] **Bloque 4 Fase 2** — `fail_under` subido de 60 → 65, `tests/test_watchlist_service.py` (11 tests), `tests/test_analytics_engine.py` (9 tests).
- [2026-05-23] **Bloque 1: OAuth Nonces + Redis Auth** — `_NonceStore` Protocol + `_TTLCacheNonceStore` / `_RedisNonceStore`. `REDIS_PASSWORD` en settings. Redis requirepass en docker-compose.
- [2026-05-23] **Bloque 7: Eliminar globals pipeline** — `_ClassifierHolder` frozen dataclass + `_load_classifiers()` con `@functools.lru_cache(maxsize=1)`.
- [2026-05-23] **Bloque 3: FK enforcement + date CHECK constraints** — `PRAGMA foreign_keys=ON`, CHECK constraints en fechas, migración `v22_fk_cascade_date_checks.py`.
- [2026-05-23] **Bloque 2: Consolidar migraciones** — `db/migrations.py` deprecado, `Makefile` targets, [[ADR-008-consolidacion-migraciones-alembic|ADR-008]].
- [2026-05-23] **Bloque 5: FAISS incremental** — método `update()`, lógica incremental vs full rebuild en `load_or_build()`.
- [2026-05-23] **Bloque 4 Fase 1** — `fail_under` subido a 60, `tests/test_contract_dto.py`.
- [2026-05-24] **P1: Pickle removal** — `dashboard/faiss_index.py`: eliminada carga pickle legacy; `load()` sólo acepta `.npz`; `_load_cached` lanza `ValueError` descriptivo si recibe `.pkl`.
- [2026-05-24] **P2: Filelock + atomic write en FaissIndex.save()** — escritura atómica con `tempfile.NamedTemporaryFile` + `os.replace()`; `FileLock(timeout=120)` para exclusión mutua entre procesos.
- [2026-05-24] **P3: SecretStr para 3 secrets** — `GOOGLE_CLIENT_SECRET`, `API_HMAC_SECRET`, `TURSO_AUTH_TOKEN` migrados a `SecretStr`; 10 call sites actualizados con `.get_secret_value()`.  <!-- pragma: allowlist secret -->
- [2026-05-24] **P4: MaxBodyMiddleware fail-loud** — `api/app.py`: `except Exception: pass` → `log.warning("max_body_middleware_unavailable", exc_info=True)`.
- [2026-05-24] **P5: ProcessPoolExecutor para 4 jobs pesados** — `daily_atom`, `recent_bulk`, `retention_cleanup`, `faiss_rebuild` ejecutados en proceso separado con `ProcessPoolExecutor(max_workers=1)` + `proc.kill()` en timeout.
- [2026-06-10] **P2: Deprecar o realinear `scheduler/run_update.py`** — Resuelto por [[ADR-012-plano-unico-orquestacion|ADR-012]]: `run_update.py` ahora delega íntegramente en `scheduler/pipeline_runs.py` (`run_daily_pipeline`, `run_bulk_pipeline`, `run_backfill_pipeline`), que ejecutan la misma secuencia canónica que `daily_atom` y `recent_bulk`. 31 tests de paridad lo verifican. Commits `9e816d6`, `6bf0b5b`.
- [2026-06-10] **P1→Cerrado: Dashboard solo vía services/ ([[ADR-013-jerarquia-materializaciones-analiticas|ADR-013]] / §3.8)** — Los 11 módulos de `dashboard/` que importaban `db.*` directamente fueron migrados a `services/`. 6 nuevos service wrappers (`audit`, `users`, `notifications`, `saved_filters`, `feature_flags`, `dlq`) + extensión de `watchlist` y `licitaciones`. Test lint `test_dashboard_db_imports.py` con 0 violaciones conocidas. `import sqlite3` eliminado de `detalle.py`. Commit `1f6bf10`.
- [2026-06-10] **P2: Métricas SQLite BUSY + tripwires [[ADR-004-sqlite-turso-vs-postgres|ADR-004]]** — 3 métricas Prometheus nuevas (`sqlite_busy_errors_total`, `db_write_duration_seconds`, `db_concurrent_writers`) instrumentadas en `db/connection.py::connect()`. Tripwires cuantitativos añadidos a [[ADR-004-sqlite-turso-vs-postgres|ADR-004]] (>10 BUSY/h → evaluar Postgres, p99 write >500ms → investigar, >3 concurrent writers → review). Commit `6bf0b5b`.
- [2026-06-10] **P2: [[ADR-013-jerarquia-materializaciones-analiticas|ADR-013]] jerarquía materializaciones analíticas** — ADR define camino canónico: SQLite = caché OLTP, Parquet = snapshot offline, DuckDB = motor opcional. Materialización solo en pipeline canónica ([[ADR-012-plano-unico-orquestacion|ADR-012]]). Commit `6bf0b5b`.
- [2026-06-10] **P3: Healthcheck reporta queue_mode** — `scheduler/healthcheck.py` ahora reporta `"queue_mode": "dramatiq" | "stub" | "inline"`. Commit `6bf0b5b`.
- [2026-06-10] **P3: Extras pyproject por rol** — `[queue]` (dramatiq+redis), `[analytics]` (duckdb), `[crypto]` (cryptography) añadidos a `pyproject.toml`. Commit `6bf0b5b`.
- [2026-06-10] **P1: DNS rebinding (TOCTOU) en webhooks** — `_resolve_and_validate()` resuelve DNS al momento del delivery (no al registrar), valida IP contra `_PRIVATE_NETWORKS`, y construye URL con IP pinneada para que `requests.post` no re-resuelva. Cierra la ventana TOCTOU. Ping ahora incluye retry con backoff exponencial (3 intentos, 0.5s/1s). Header `Host:` preservado para TLS SNI.
- [2026-06-10] **P2: QUEUE_MODE explícito con fail-fast** — Setting `QUEUE_MODE` en `config/settings.py` (`auto`|`dramatiq`|`inline`). Si `QUEUE_MODE=dramatiq` y falta `DRAMATIQ_BROKER_URL` o Redis no conecta → `RuntimeError` inmediato (fail-fast). Modo `inline` fuerza ejecución síncrona sin intentar dramatiq.
- [2026-06-10] **P2: Silent `except Exception: pass` → log** — 15 ocurrencias en 9 archivos de producción reemplazadas con `log.debug(..., exc_info=True)`: tracing, histograms, drift_report, analytics_engine, llm client, webhooks repo, watchlist repo, api_keys repo, db analytics.
- [2026-06-10] **P2: Métrica NULL % por campo crítico en parser CODICE** — `parser_entries_total` (Counter) + `parser_field_null_total` (Counter por field) en `runtime_metrics.py`. Instrumentado en `parse_entry()` para 5 campos críticos: organo_contratacion, importe, cpv, estado, fecha_publicacion. Permite alertar en Grafana si un cambio de schema del PLACSP rompe la extracción silenciosamente.
- [2026-06-10] **P3: Escape wildcards LIKE en queries** — `_escape_like()` helper en `db/repositories/licitaciones.py` escapa `%` y `_` del input de usuario antes de construir patrones LIKE. Aplicado en 5 sitios (listados, tech, PDF export, LIKE fallback, /ask fallback). Previene resultados incorrectos al buscar textos con wildcards.
- [2026-06-10] **P3: Retry en ping de webhooks** — Incluido en el fix de DNS rebinding: 3 intentos con backoff exponencial (0.5s, 1s). Respuesta incluye `attempts` count.
- [2026-06-10] **P3: Consolidar tests de rollback** — Renombrados `test_migration_rollbacks.py` → `test_rollback_legacy_migrations.py` y `test_migrations_rollback.py` → `test_rollback_alembic_migrations.py` para claridad. No son duplicados: cubren sistemas distintos (legacy vs Alembic).
- [2026-06-10] **P3: Hook graph stale tras edits .py** — Ya implementado en `.claude/settings.json` como tercer bloque PreToolUse (matcher `Edit|Write|MultiEdit`). Crea `graphify-out/.graph_stale` al editar `.py`; `/graph-refresh` lo borra tras update exitoso. Funcional con el mismo efecto que PostToolUse.
- [2026-06-10] **P3: Dynamic recharts en 10 páginas frontend** — Extraídos 32 chart blocks de 10 páginas a 10 chart subcomponents (`components/charts/*-charts.tsx`). Cada página ahora importa sus charts con `next/dynamic({ ssr: false })` + Skeleton fallback, eliminando recharts del bundle inicial. 0 imports estáticos de recharts en páginas (solo en subcomponentes). `tsc --noEmit` 0 errores.
- [2026-06-10] **P3: Split archivos God** — `dashboard/stats/_base.py` (1070→794 LOC): `risk_flags` + `score_oportunidad` extraídos a `_scoring.py` (273 LOC). Frontend: charts extraídos a subcomponentes (cubierto por el ítem dynamic recharts). `db/migrations.py`: evaluado, no purgable (lo usa `init_db` en runtime), congelado per [[ADR-008-consolidacion-migraciones-alembic|ADR-008]]. `ml_classifier.py` (880): evaluado, cohesivo (ya delega a `ml_pipeline.py`), no merece split forzado.
- [2026-05-24] **P6: sys.path hack eliminado** — `scheduler/retention.py` creado con lógica completa; `scripts/retention_cleanup.py` reescrito como thin CLI wrapper.
- [2026-05-24] **P7: DB pool timeout** — `_pool.get(timeout=acquire_timeout)` con default 10s desde `DB_POOL_TIMEOUT`; `queue.Empty` → `RuntimeError` descriptivo.
- [2026-05-24] **P8: Mypy overrides cerrados para 5 módulos** — `config.settings`, `shared.auth_core`, `api.auth`, `db.audit`, `db.totp` removidos de `ignore_errors`; errores de tipo corregidos en los 5 módulos.
- [2026-05-24] **P9: Prometheus metrics para scheduler, DB pool, FAISS** — `scheduler_job_total`, `scheduler_job_duration_seconds`, `db_pool_acquire_timeout_total`, `faiss_rebuild_total`, `faiss_rebuild_duration_seconds` en `observability/runtime_metrics.py`; instrumentados en `scheduler/loop.py`, `db/connection.py`, `dashboard/faiss_index.py`.
- [2026-05-24] **P10: Tests flakiness eliminado** — `tests/test_faiss_index.py` migrado de pickle a `.npz`; patch target corregido de `faiss_index.encode_texts` → `dashboard.embeddings.encode_texts`; `time.sleep` aumentado de 10ms→50ms en `test_shared_cache.py`.
- [2026-05-24] **P11: uv.lock generado + Makefile targets** — `uv.lock` generado (135 paquetes); targets `lock-uv` y `install-uv` añadidos al Makefile.
- [2026-05-29] **Fase 0: Docker + starlette** — Healthcheck path corregido en `Dockerfile.api:61` → `/api/v1/health`; `.venv/` en `.dockerignore`; `starlette>=1.0.1,<2` pinned; `--force-reinstall` eliminado.
- [2026-05-29] **Fase 1: Deps** — `cachetools>=5.3.0,<8` y `brotli-asgi>=1.4.0,<2` añadidos; `libsql` rango estrechado a `<0.3`; `duckdb` re-añadido a `ignore_missing_imports` (no tiene stubs).
- [2026-05-29] **Fase 2: Security** — CORS fail-closed (wildcard solo non-prod/staging); `/metrics` auth endurecido (API key obligatoria en prod/staging); HMAC truncation documentada.
- [2026-05-29] **Fase 3: Observability** — `configure_sentry` wired en `api/app.py` y `scheduler/loop.py`; `OTEL_SAMPLE_RATIO` default `0.01` → `0.1`; metrics imports top-level en loop.
- [2026-05-29] **Fase 4: Scheduler refactor** — Job registry pattern (`scheduler/jobs/` package); persistent `ProcessPoolExecutor`; `shutdown(cancel_futures=True)` reemplaza `executor._processes` hack; 20 tests en `test_loop.py`.
- [2026-05-29] **Fase 5.1: Batch upsert** — `replace_adjudicaciones_batch()` en `db/upsert.py` (una transacción para N licitaciones); pipeline bulk y daily actualizados.
- [2026-05-29] **Fase 6: Full strict typing** — Eliminados 3 bloques de override mypy (52 módulos promovidos a strict); 149 errores corregidos en 40 archivos (unused-ignore, type-arg, no-any-return, pandas narrowing, arg-type, misc); `shared/py.typed` creado. 375 archivos pasan `mypy --strict`.
- [2026-07-04] **Scoring genérico sin SAP** — Eliminadas constantes hardcodeadas `_SAP_MODULES`/`_SAP_SERVICES_PORTFOLIO`/`_S4HANA_KEYWORDS`. Dimensiones nuevas: `competencia` (media ofertas CPV-4, 24 meses), `margen` (`predicciones_baja.p50` + fallback histórico), `afinidad` (keywords configurables via `SCORING_AFINIDAD_KEYWORDS`, vacío=omitida con redistribución de peso). Política dato-faltante=neutral sin penalización de cobertura. `settings.SCORING_WEIGHTS` con validación de suma. RFC `2026-07-04-rfc-scoring-generico.md`.
- [2026-07-04] **Reduccion de superficie operativa (F1-F8)** — Tripwires de persistencia reconectados via `ops_events` + healthcheck (tabla BD, reemplaza contadores Prometheus por-proceso). FAISS eliminado (F3): `/search` usa FTS5/BM25+LIKE, `faiss-cpu` quitado de extras. Dramatiq eliminado (F4): `scheduler/queue.py` borrado, extra `[queue]` y job CI quitados. Redis desacoplado de docker-compose local (F5): profile `redis` opt-in. Staging borrado (F7): `deploy-staging.yml` + `docker-compose.staging.yml`; secrets `STAGING_*` a borrar manualmente en GitHub Settings. Rename a Tenderflow (F8): USER_AGENT, OTEL_SERVICE_NAME, ADR-015. `vercel_app.py` + `tenderflow/__init__.py` borrados (F2).

---

## Plantilla nueva entrada

```markdown
### [P0|P1|P2|P3] Título corto en imperativo
- **Área:** paquete/subárea
- **Problema:** 1-2 frases describiendo qué está mal y por qué importa.
- **Acceptance criteria:**
  - Bullet verificable 1
  - Bullet verificable 2
- **Files de partida:** [path1](../path1), [path2](../path2)
- **Riesgo:** bajo | medio | alto — razón breve.
```
