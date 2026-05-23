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
- **Problema:** ~30+ módulos del dashboard tienen `disallow_untyped_defs = false` en `pyproject.toml` (sección `[[tool.mypy.overrides]]`). Solo `dashboard.bootstrap` es strict. Los agentes pierden inferencia útil y los bugs de tipos pasan desapercibidos.
- **Progreso parcial (2026-05-23):** Se eliminó `dashboard.auth` del override en Fase 5 (code quality). Quedan ~29 módulos.
- **Acceptance criteria:**
  - Añadir type hints a todas las funciones públicas de al menos `dashboard/data_loader.py`, `dashboard/cache.py`, `dashboard/router.py`.
  - Eliminar el override correspondiente en `pyproject.toml` por cada módulo migrado.
  - `make typecheck` verde.
- **Files de partida:** [pyproject.toml](../pyproject.toml) (sección mypy overrides), [dashboard/data_loader.py](../dashboard/data_loader.py), [dashboard/cache.py](../dashboard/cache.py).
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

### Reducir SQL manual con `S608` suppress en scraper ML
- **Área:** `scraper/ml_*`
- **Problema:** `scraper/ml_classifier.py` y `scraper/ml_pipeline.py` tienen SQL construido manualmente con suppress de Bandit (S608, posible SQL injection). Aunque los inputs son controlados, es deuda técnica.
- **Acceptance criteria:**
  - Migrar a queries parametrizadas (`?` placeholders) o a un repositorio en `db/repositories/ml.py`.
  - Eliminar los `# noqa: S608`.
  - `make typecheck && bandit -r scraper/` verde.
- **Files de partida:** [scraper/ml_classifier.py](../scraper/ml_classifier.py), [scraper/ml_pipeline.py](../scraper/ml_pipeline.py).
- **Riesgo:** medio — toca ruta de entrenamiento; necesita tests integration verdes después.

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
