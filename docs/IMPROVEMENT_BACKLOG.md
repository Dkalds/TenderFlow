# Improvement Backlog

Lista viva de mejoras conocidas, priorizadas. **Diseñada para que un agente pueda elegir un ítem y trabajarlo sin pedir contexto extra al usuario.**

## Convenciones

- **Prioridad**: P0 (urgente / bloquea) · P1 (alta) · P2 (media) · P3 (nice-to-have).
- **Riesgo**: bajo (cambio aislado) · medio (afecta varios módulos) · alto (toca core / migra schema / cambia contrato).
- Si añadís un ítem nuevo, copiá la plantilla del final.
- Al cerrarlo, no lo borres: movélo a la sección **Cerrados** abajo, con la PR/commit que lo resolvió.

---

## P1 — Alta

### Strict typing en `dashboard/`
- **Área:** `dashboard/`
- **Problema:** ~30+ módulos del dashboard tienen `disallow_untyped_defs = false` en `pyproject.toml`. Solo `dashboard.bootstrap` es strict.
- **Progreso (2026-05-23):** `dashboard.cache` y `dashboard.data_loader` cerrados (Bloque 10a). `dashboard.router` y `dashboard.filters.*` confirmados tipados (Bloque 10b). Quedan ~27 módulos.
- **Acceptance criteria:**
  - Añadir type hints a todas las funciones públicas de al menos `dashboard/data_loader.py`, `dashboard/cache.py`, `dashboard/router.py`.
  - Eliminar el override correspondiente en `pyproject.toml` por cada módulo migrado.
  - `make typecheck` verde.
- **Files de partida:** [pyproject.toml](../pyproject.toml) (sección mypy overrides).
- **Riesgo:** medio — typing puede revelar bugs latentes; hacer módulo por módulo.

### `py.typed` marker para consumo externo del paquete
- **Área:** `shared/`, root del paquete
- **Problema:** El proyecto no expone `py.typed`, así que consumidores externos (si alguno importa `shared/` o `services/` como library) no obtienen tipos.
- **Acceptance criteria:**
  - Añadir archivo vacío `shared/py.typed`.
  - Verificar que `pyproject.toml` lo incluye en el package data.
- **Files de partida:** [pyproject.toml](../pyproject.toml).
- **Riesgo:** bajo.

---

## P2 — Media

### ~~Reducir SQL manual con `S608` suppress~~ — CERRADO
- **Estado:** Resuelto en Bloque 9 (2026-05-23). Ver sección Cerrados.

### Documentar la fachada `db.database`
- **Área:** `db/`
- **Problema:** `db/database.py` es fachada sobre `db/connection.py`, `db/schema.py`, `db/upsert.py`. Un agente nuevo tarda en entender el split. No hay docstring que explique qué hay en cada submódulo.
- **Acceptance criteria:**
  - Docstring de módulo en `db/database.py` listando los 3 submódulos y qué reexporta de cada uno.
  - Sección breve en [AGENT_PLAYBOOK.md](AGENT_PLAYBOOK.md) o ADR-001 sobre el patrón.
- **Files de partida:** [db/database.py](../db/database.py).
- **Riesgo:** bajo — solo docs.

### Instalar stubs de pandas para mypy
- **Área:** `pyproject.toml` / typing
- **Problema:** mypy reporta `Library stubs not installed for "pandas"` en ~18 archivos (dashboard, scheduler, scraper, services). Impide type-checking completo de esos módulos.
- **Acceptance criteria:**
  - Añadir `pandas-stubs` a dependencias de desarrollo.
  - mypy no reporta `import-untyped` para pandas.
- **Files de partida:** [pyproject.toml](../pyproject.toml).
- **Riesgo:** bajo — solo dev dependency.

---

## P3 — Nice to have

### Hook PostToolUse para marcar graph como stale tras edits a `.py`
- **Área:** `.claude/settings.json`
- **Problema:** Hoy el agente debe acordarse de correr `graphify update .` tras editar (lo dice AGENTS.md sección 5, pero es manual). Un hook PostToolUse puede dejar un flag `graphify-out/.graph_stale` cuando se edita un `.py`, y `/graph-refresh` lo borra. Detecta drift automáticamente.
- **Acceptance criteria:**
  - Añadir un bloque PostToolUse en `.claude/settings.json` con matcher `Edit|Write|MultiEdit` que ejecute:
    ```bash
    python3 -c "import json,sys,os,pathlib;d=json.load(sys.stdin);fp=(d.get('tool_input',d) or {}).get('file_path','');skip=any(x in fp for x in ('.venv','graphify-out','.mypy_cache','.pytest_cache','.ruff_cache','__pycache__','htmlcov','node_modules'));ok=fp.endswith('.py') and not skip and os.path.isdir('graphify-out');pathlib.Path('graphify-out/.graph_stale').touch() if ok else None" 2>/dev/null || true
    ```
  - Actualizar `/graph-refresh` (ya lo hace) para borrar el flag tras update exitoso.
  - Probar: editar un `.py`, verificar que existe `graphify-out/.graph_stale`; correr `/graph-refresh`; verificar que se borró.
- **Files de partida:** [.claude/settings.json](../.claude/settings.json) (ya tiene un PreToolUse; añadir PostToolUse manteniéndolo).
- **Riesgo:** bajo — el hook es silencioso (`|| true`), no bloquea ediciones. **Self-modification: requiere que el humano lo añada (el agente no puede editar `.claude/settings.json` por política de seguridad).**

---

## Cerrados

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
- [2026-05-23] **Bloque 2: Consolidar migraciones** — `db/migrations.py` deprecado, `Makefile` targets, ADR-008.
- [2026-05-23] **Bloque 5: FAISS incremental** — método `update()`, lógica incremental vs full rebuild en `load_or_build()`.
- [2026-05-23] **Bloque 4 Fase 1** — `fail_under` subido a 60, `tests/test_contract_dto.py`.
- [2026-05-24] **P1: Pickle removal** — `dashboard/faiss_index.py`: eliminada carga pickle legacy; `load()` sólo acepta `.npz`; `_load_cached` lanza `ValueError` descriptivo si recibe `.pkl`.
- [2026-05-24] **P2: Filelock + atomic write en FaissIndex.save()** — escritura atómica con `tempfile.NamedTemporaryFile` + `os.replace()`; `FileLock(timeout=120)` para exclusión mutua entre procesos.
- [2026-05-24] **P3: SecretStr para 3 secrets** — `GOOGLE_CLIENT_SECRET`, `API_HMAC_SECRET`, `TURSO_AUTH_TOKEN` migrados a `SecretStr`; 10 call sites actualizados con `.get_secret_value()`.  <!-- pragma: allowlist secret -->
- [2026-05-24] **P4: MaxBodyMiddleware fail-loud** — `api/app.py`: `except Exception: pass` → `log.warning("max_body_middleware_unavailable", exc_info=True)`.
- [2026-05-24] **P5: ProcessPoolExecutor para 4 jobs pesados** — `daily_atom`, `recent_bulk`, `retention_cleanup`, `faiss_rebuild` ejecutados en proceso separado con `ProcessPoolExecutor(max_workers=1)` + `proc.kill()` en timeout.
- [2026-05-24] **P6: sys.path hack eliminado** — `scheduler/retention.py` creado con lógica completa; `scripts/retention_cleanup.py` reescrito como thin CLI wrapper.
- [2026-05-24] **P7: DB pool timeout** — `_pool.get(timeout=acquire_timeout)` con default 10s desde `DB_POOL_TIMEOUT`; `queue.Empty` → `RuntimeError` descriptivo.
- [2026-05-24] **P8: Mypy overrides cerrados para 5 módulos** — `config.settings`, `shared.auth_core`, `api.auth`, `db.audit`, `db.totp` removidos de `ignore_errors`; errores de tipo corregidos en los 5 módulos.
- [2026-05-24] **P9: Prometheus metrics para scheduler, DB pool, FAISS** — `scheduler_job_total`, `scheduler_job_duration_seconds`, `db_pool_acquire_timeout_total`, `faiss_rebuild_total`, `faiss_rebuild_duration_seconds` en `observability/runtime_metrics.py`; instrumentados en `scheduler/loop.py`, `db/connection.py`, `dashboard/faiss_index.py`.
- [2026-05-24] **P10: Tests flakiness eliminado** — `tests/test_faiss_index.py` migrado de pickle a `.npz`; patch target corregido de `faiss_index.encode_texts` → `dashboard.embeddings.encode_texts`; `time.sleep` aumentado de 10ms→50ms en `test_shared_cache.py`.
- [2026-05-24] **P11: uv.lock generado + Makefile targets** — `uv.lock` generado (135 paquetes); targets `lock-uv` y `install-uv` añadidos al Makefile.

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
