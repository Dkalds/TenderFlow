---
tags: [plan, arquitectura, multi-agente]
---

# Plan de arquitectura 2026-09 — ejecutable por streams

Redactado el 2026-09-02 a partir del diagnóstico de arquitecto de esa misma
fecha (verificado contra el código, los logs de GitHub Actions y el estado de
producción).

**Estado: EJECUTADO PARCIALMENTE el 2026-09-04** en la rama
`claude/arq-2026-09`. Qué aterrizó, qué no y con qué controles está en el
**§8**, que es la sección que hay que leer antes que ninguna otra: tres ítems de
S5 quedaron fuera y hay cuatro migraciones escritas y **sin aplicar** contra
ninguna base de datos. Las decisiones de §3 se resolvieron por la propuesta que
cada una llevaba anotada; las que exigen tocar infraestructura real siguen
abiertas y están listadas en §8 y §6bis.

Mismo contrato que [2026-08-plan-saneamiento.md](2026-08-plan-saneamiento.md):
cada stream se ejecuta en su propia rama por un agente independiente, este
documento es la fuente única de alcance y criterios de aceptación, y un agente
que toma un stream trabaja **solo** los archivos de ese stream.

## 0. Alcance

Cubre las siete roturas de producción y las seis áreas estructurales del
diagnóstico, **salvo el backup y el restore drill**, que el mantenedor dejó
fuera de este plan el 2026-09-02 (workflows `backup.yml` y `restore-drill.yml`,
causa: `pg_dump` sin CA en el runner con `sslmode=verify-full`). Ningún stream
de aquí toca esos dos ficheros.

Convenciones de esfuerzo: **S** menos de un día de agente · **M** uno a tres
días · **L** varias PRs. Los gates de AGENTS.md §6 se marcan como **[§6]** y
requieren OK explícito salvo que §3 los pre-autorice.

## 1. Hechos verificados (2026-09-02)

Los agentes ejecutores asumen ESTO, no lo que digan docs anteriores:

1. Producción está en `v97_pursuit_comments`; la cabeza del repo es `v98`.
   `migrate.yml` corrió el 2026-09-02 13:33 sobre master **antes** del merge de
   #258. La ficha pública ya devuelve 404 a lo no tecnológico mientras hubs y
   sitemap sirven la vista vieja.
2. `scrape-daily.yml` está en rojo desde el 2026-09-01 12:00 porque el paso
   `llm_models_canary` lanza `RuntimeError` por `z-ai/glm-5.2`. Los otros 14
   pasos del cierre terminan `ok`. El fix del catálogo es #259.
3. `train-predictivos.yml` (cron mensual, primera ejecución programada el
   2026-09-01) falló con `ValueError: time data '19-12-10'` en
   `services/ml/features.py::_fecha_dt`. El modelo de baja nunca se reentrenó
   por esta vía.
4. `security.yml` está en rojo desde el 2026-08-17: Semgrep bloquea por
   `run-shell-injection` en `.github/workflows/deploy.yml:100` (interpolación
   `${{ inputs.skip_smoke }}` y `${{ job.status }}` dentro de `run:`). Trivy
   reporta CVE alto en el `pip` de la imagen de la API. Hay dos findings
   Python más abiertos en Code Scanning (`scripts/smoke_prod.py:133`,
   `scraper/connectors/regional_rss.py:12`).
5. `services/tech_signal.py::merge_tech_signals` falla con `KeyError('SAP')`
   (y `IBM`, `MICROSOFT`, `OPENTEXT`, `SALESFORCE`, `META4`) en ~33
   expedientes por pasada, a nivel `warning`. Causa: `scraper/pipeline.py:223`
   escribe `ml_tecnologias` en la ingesta sin fila en
   `licitacion_tecnologia_score`, y `_build_merge_result` indexa
   `full_scores[t]` para toda tecnología predicha.
6. `scraper/pipeline.py` sigue siendo escritor de producción vía
   `scheduler/dlq_retry.py:106-113` (`process_month`) y
   `scheduler/pipeline_runs.py:772-775` (`backfill`). Ese camino no escribe
   linaje, historial, lotes ni documentos, y `db/upsert.py:230-232` no hace
   COALESCE de `inclusion_reason`/`filter_version`/`analysis_universe`, así que
   una re-ingesta legacy los borra. Ya existe un backfill por conectores en
   `scripts/backfill_documentos.py`.
7. `TechnologyClassifier` (`ML_TECH_ENABLED=True`) no lo entrena ni publica
   ningún workflow; `scraper/ml_training.py:501-503` devuelve
   `skipped_no_model` y el paso `ml_tecnologias` reporta `ok`. La API en Render
   no tiene disco ni llamada de descarga: `api/model_cache.py` carga un
   fichero que no existe y `POST /models/{name}/activate/{version}` no cambia
   lo servido.
8. `render.yaml` se declara «SIN VERIFICAR desde 2026-08-04»; la memoria de
   sesión del 2026-08-28 constató `autoDeploy: yes` y plan `standard` en el
   dashboard. No hay `alerting:` en `observability/prometheus.render.yml` ni
   Alertmanager en ningún sitio; dos reglas van etiquetadas `critical`.
9. `DELETE /api/v1/me` exige CSRF (vía `require_recent_session` →
   `require_any_auth`, `api/routes/dual_auth.py:46-68`) y
   `web/src/app/(dashboard)/mi-cuenta/page.tsx:77` no lo envía.
10. `.claude/worktrees/` tiene 19 directorios y `git worktree list` registra 8.
    Es la causa del filesystem lento de la máquina del mantenedor.
11. Otra sesión trabaja en paralelo sobre el árbol principal: el fix del
    drift ya está commiteado (`4ac447a`) y hay cambios sin commitear en
    `services/tech_signal.py`, `db/repositories/tecnologia_pliego.py`,
    `scheduler/pipeline_runs.py` y sus tests que implementan O0.5 (`.get(t,
    0.0)` en el merge) más un `merge_many_with_lock` por lote con log de
    duración. **Ningún stream toca ni revierte ese trabajo**; O0.5 se da por
    tomado y O0.2 debe rebasar sobre él.

## 2. Olas

- **Ola 0 — Parar la hemorragia.** Ítems pequeños, sin decisión previa, un PR
  por ítem o agrupados por fichero. Objetivo: todos los workflows programados
  en verde siete días seguidos y ninguna pérdida silenciosa de datos.
- **Ola 1 — Streams paralelos S1..S7.** Trabajo estructural sin gate o con
  gate pre-autorizado en §3.
- **Ola 2 — Lo que depende de una decisión o de una migración.** Cada ítem
  lleva la decisión que lo desbloquea.

## 3. Decisiones del mantenedor (pendientes)

| Id | Decisión | Desbloquea |
|---|---|---|
| D1 | ¿Entra la señal ML/LLM/pliego en el universo público? Propuesta: sí, cuando `ml_tecnologias` no está vacío **y** el método tiene score sobre umbral; la revisión `v99` reconstruye `licitaciones_canonicas` con ese predicado. | S1.6 |
| D2 | `TechnologyClassifier`: publicarlo con workflow propio (como `train-model.yml`) o poner `ML_TECH_ENABLED=False` y que el paso reporte `skipped`, nunca `ok`. Propuesta: publicar; el evaluador y el golden ya existen. | S3.1 |
| D3 | ¿La API sirve modelos? Propuesta: sí, con un único resolvedor (`resolve_active_artifact`) y descarga a directorio escribible; alternativa: retirar `/models/*/activate` y `/explain`. | S3.2 |
| D4 | Render: vincular el Blueprint en ventana o replicar a mano `healthCheckPath` y anotar en `render.yaml` que el dashboard manda. | S6.1 |
| D5 | Alertas: desplegar Alertmanager como `pserv` con receptor de email más un segundo canal, o retirar `alert_rules.yml` y declarar que el único plano es `ops_events` + email. Propuesta: Alertmanager. | S6.3 |
| D6 | Borrar las 17 rutas del dashboard que `next.config.ts` redirige (no ocultar: borrar). Propuesta: sí. | S5.3 |
| D7 | Endpoints asíncronos de export (`POST /exports`, `GET /exports/{id}`): retirar del contrato (**RFC**, contrato breaking) o mover el store a Redis. Propuesta: retirar. | S4.9 |
| D8 | CSRF: adoptar `shared/csrf.py` (con `kid` y rotación) como único formato de token (**RFC**, decisión de auth) o borrarlo y quedarse con el HMAC plano. Propuesta: adoptar. | S4.6 |
| D9 | Matriz CI Python: quitar 3.12 del PR (producción es 3.13) y dejarlo en un cron semanal. | S6.5 |
| D10 | Gates §6 pre-autorizados para este plan: migración `v99` (MV universo, S1.6); migración `v100` (`primera_extraccion`, S1.7); edición de `scrape-daily.yml`, `scrape-bulk.yml`, `pliegos.yml`, `deploy.yml`, `ci.yml`, `security.yml`, `train-predictivos.yml`, `migrate.yml` en los términos de S6 y O0; `docker/Dockerfile.api` (pip); `.gitignore`, `.dockerignore`; retirada de dependencias d3 y `react-virtuoso` (S5.6). Todo lo demás sigue pidiendo OK puntual. | O0.4, S1, S5, S6 |

Mientras D1..D9 no estén cerradas, los ítems que las citan no se empiezan. Un
agente que necesite una decisión no tomada la deja escrita en el PR y se
detiene ahí.

---

## 4. Ola 0 — Parar la hemorragia

Sin gate salvo donde se indica. Orden sugerido: O0.1 y O0.9 son acciones del
mantenedor y van primero; el resto es paralelo.

| Id | Qué | Ficheros | Esf. | Gate |
|---|---|---|---|---|
| O0.1 | **Lanzar `migrate.yml`** (`mode=plan` y luego `mode=apply`, `target=head`) y comprobar que `/publico/hubs` deja de listar CPV no tecnológicos y que la franja de la portada baja a la cifra del universo. | acción del mantenedor | S | — |
| O0.2 | **Severidad por paso en el cierre.** `CANONICAL_STEPS` gana un mapa `STEP_TIER = {"bloqueante", "advisory"}`; `llm_models_canary`, `anomaly_checks`, `drift_checks` y `sap_active_learning` son advisory: notifican por email pero **no** ponen `pipeline_post_ingestion_steps_failed` ni el job en rojo. Los bloqueantes siguen igual. Test que fija qué pasos son de cada tier. | `scheduler/pipeline_runs.py`, `scheduler/run_update.py`, tests | S | — |
| O0.3 | **Retrain de predictivos.** `_fecha_dt` pasa a usar `shared/dates.to_iso_date` y descarta la fila con log `ml_dataset_fecha_invalida` en vez de abortar; se añade a `scripts/audit_domain_truth.py` el recuento de `fecha_publicacion` no ISO con umbral; relanzar `train-predictivos.yml` a mano tras el merge. | `services/ml/features.py`, `services/ml/baja_model.py`, `scripts/audit_domain_truth.py`, tests | S | relanzar workflow: mantenedor |
| O0.4 | **Verde en `security.yml`.** En `deploy.yml` el paso «Resumen» lee `inputs.skip_smoke` y `job.status` desde `env:` en vez de interpolarlos en `run:`; `docker/Dockerfile.api` añade `pip install --upgrade pip` en la etapa runtime; `scripts/smoke_prod.py:133` valida esquema y host antes de `urlopen`; `regional_rss.py:12` pasa a `defusedxml` (ya es dependencia transitiva; si no, `lxml` con `resolve_entities=False`). | `.github/workflows/deploy.yml`, `docker/Dockerfile.api`, `scripts/smoke_prod.py`, `scraper/connectors/regional_rss.py` | S | **[§6]** workflow y Dockerfile: pre-autorizado en D10 |
| O0.5 | **Merge de señal de pliego tolerante.** `_build_merge_result` trata una tecnología predicha sin score como score `0.0`; test con `ml_tecnologias='SAP'` y `licitacion_tecnologia_score` vacío. La raíz (quién escribe `ml_*`) se cierra en S1.4. **En curso en otra sesión** (hecho 11): no duplicar. | `services/tech_signal.py`, `db/repositories/tecnologia_pliego.py`, tests | S | en curso |
| O0.6 | **`ml_scoring` deja de depender del disco del runner.** `precompute_ml_proba` llama a `SAPClassifier.ensure_downloaded()` antes de `is_available()`; si no hay artefacto, el paso devuelve `skipped` (no `ok`) y el resumen del cierre lo muestra. | `scraper/ml_training.py`, `scheduler/pipeline_runs.py` | S | — |
| O0.7 | **Borrado GDPR de cuenta.** `mi-cuenta/page.tsx` usa `apiMutate` (adjunta `X-CSRF-Token`); el mismo barrido cubre `login/page.tsx:531` y `restablecer-contrasena/page.tsx:39,61`. Test e2e en `critical-workflows.spec.ts` que ejecute el borrado contra la API real de CI. | `web/src/app/(dashboard)/mi-cuenta/page.tsx`, `web/src/app/login/page.tsx`, `web/src/app/restablecer-contrasena/page.tsx`, `web/e2e/critical-workflows.spec.ts` | S | — |
| O0.8 | **Calendario ICS con ámbito de organización.** `_calendario_rows` sale de `api/routes/exports.py` a `WatchlistRepository.list_items_calendario(organization_id, user)` con el mismo predicado de visibilidad que `list_items`; `exports.py` sale de la whitelist TID251. | `api/routes/exports.py`, `db/repositories/watchlist.py`, `pyproject.toml`, tests | S | — |
| O0.9 | **Worktrees.** `git worktree prune` y borrado de los 11 directorios huérfanos de `.claude/worktrees/` tras comprobar que no tienen cambios sin commitear. | acción del mantenedor | S | — |
| O0.10 | **Higiene de árbol.** `.gitignore`: `data/*` con `!data/.gitkeep` y `!data/README.md` si existe; `.dockerignore`: `web/`, `node_modules/`, `.github/`, `.claude/`. | `.gitignore`, `.dockerignore` | S | **[§6]** pre-autorizado en D10 |

**Verificación de la ola:** siete días con `scrape-daily`, `pliegos`,
`ml-scoring`, `healthcheck`, `domain-truth`, `smoke` y `security` en verde;
`train-predictivos` relanzado en verde; `gh api code-scanning/alerts` sin
alertas abiertas de Semgrep; log del cierre sin `tech_signal_merge_failed`.

---

## 5. Ola 1 — Streams

| Stream | Rama | Migración | Merge |
|---|---|---|---|
| S1 Verdad del dato | `claude/s1-dato` | v99, v100 (Ola 2) | tras S2 (comparten `db/upsert.py`) |
| S2 Ingesta | `claude/s2-ingesta` | no | 1º entre S1/S2/S3 |
| S3 ML | `claude/s3-ml` | no | tras S2 (comparten `pipeline_runs.py`) |
| S4 Backend | `claude/s4-backend` | no | libre |
| S5 Frontend | `claude/s5-frontend` | no | libre |
| S6 Plataforma | `claude/s6-plataforma` | no | libre |
| S7 Documentación | `claude/s7-docs` | no | último (cita a los demás) |

**Propiedad exclusiva de ficheros:**

- `db/sql_fragments.py`, `shared/estados.py`, `db/repositories/tecnologia_pliego.py`: S1.
- `db/upsert.py`: S2 primero (COALESCE de linaje), S1 rebasa (propiedad de `ml_*`).
- `scraper/pipeline.py`, `scheduler/dlq_retry.py`, `scraper/connectors/**`: S2.
- `scheduler/pipeline_runs.py`: O0.2 → S2 → S3, en ese orden de merge.
- `scraper/ml_training.py`, `services/ml/**`, `api/model_cache.py`, `scheduler/drift_*.py`: S3.
- `api/**`, `services/analytics/**`, `db/repositories/aggregates.py`, `db/repositories/adjudicaciones.py`, `shared/dto.py`, `shared/csrf.py`: S4.
- `web/**`: S5 (salvo O0.7, que va antes).
- `.github/workflows/**`, `render.yaml`, `observability/**`, `config/settings.py`, `docker/**`, `scripts/check_*.py`: S6.
- `docs/**` salvo el backlog: S7. El backlog lo edita cada stream solo en sus ítems.

### S1 — Verdad del dato

**Objetivo:** una sola definición ejecutable de tecnología, universo, canónica y
abierta, con dueño y con test que impida copias.

Sin gate:

1. **Predicados con dueño.** Sustituir las ~25 copias literales del predicado
   de universo (`scheduler/kpi_precompute.py` ×16, `scheduler/aggregates_precompute.py:116`,
   `db/domain_truth_audit.py:26`, `db/repositories/pricing.py:51`,
   `db/repositories/ml_dataset.py:60`, `services/sql_fragments.py:63`) por
   `db.sql_fragments.universo_tecnologico_sql` o `TECHNOLOGY_OBSERVED_SQL`, y
   las 3 copias del anti-join de duplicados (`domain_truth_audit.py:31`,
   `ml_dataset.py:57,414`) por `exclude_duplicados_sql`. Decidir en el PR qué
   forma usa `kpi_snapshots` (propuesta: la ancha, la misma que la superficie
   pública) y anotar el cambio de cifra esperado en el resumen.
2. **Test de literales.** Extender `tests/test_dedup_guardrail.py` con un
   escáner de `COALESCE(analysis_universe` y
   `FROM licitaciones_duplicados WHERE status` fuera de `db/sql_fragments.py`
   y de `db/alembic/versions/`, con `_PENDIENTES_MAX = 0`.
3. **Cuatro grafías de «abierta».** `db/repositories/licitaciones.py:209,416-418`
   y `db/repositories/aggregates.py:1584,1729` pasan a `shared.estados.abierta_sql()`.
4. **`ml_*` pertenece al plano ML.** `db/upsert.py`: `ml_tecnologias`,
   `ml_proba_max`, `ml_tech_principal` salen del `UPDATE SET` de re-ingesta
   (solo se escriben en INSERT); `scraper/pipeline.py::_apply_tech_prediction`
   persiste además las filas de `licitacion_tecnologia_score` en la misma
   transacción o no anota nada. Con esto el barrido `tech_signal_merge` deja de
   ser reparación y O0.5 queda como red.
5. **Fragmentos privados duplicados.** `_fold_expr` y `_iso_guard` de
   `aggregates.py` pasan a `db/sql_fragments.py` y los tres sitios que los
   re-tipean (`sql_fragments.py:172-176`, `adjudicaciones.py:350`,
   `agenda.py:26-31`) los importan.

Ola 2 (con decisión o gate):

6. **[D1][§6 v99] Universo con señal ML.** `universo_tecnologico_sql` admite
   `ml_tecnologias` no vacío con score sobre `PLIEGO_TECH_MIN_SCORE`; revisión
   `v99` reconstruye `licitaciones_canonicas` con la permuta construir-al-lado
   de `v98`; `tests/test_mv_canonicas_definicion.py` mueve `_RUTA_VISTA` a v99.
   Escribir la regla de precedencia (keyword → ML → LLM → pliego) en el docstring
   del fragmento y en ADR-026 (S7).
7. **[§6 v100] Clave canónica inmutable.** Columna `primera_extraccion`
   (rellenada con `MIN(fecha_extraccion)` de `licitaciones_history` y, si no
   hay, con `fecha_extraccion`), el upsert solo la escribe en INSERT, y
   `periodo_publicacion_sql` y `_rango_canonico_sql` la usan en lugar de
   `fecha_extraccion`. Índice `idx_lic_clave_canonica` recreado
   `CONCURRENTLY` en revisión aparte, como `v92`.
8. **Una definición de «mismo contrato».** `detect_republicaciones`
   (`services/dedupe.py`) y `fila_canonica_sql` usan los mismos cuatro
   componentes: unificar en un único helper Python + SQL con test de paridad,
   y decidir si una republicación `pending` se oculta o se muestra. La decisión
   queda en ADR-026.

**Verificación:** `make check`; `tests/test_dedup_guardrail.py` con
`_PENDIENTES_MAX = 0` en las dos categorías nuevas; `make audit-truth-check`
contra BD real antes y después de S1.1 con el delta de cifras anotado en el PR.
**Riesgo:** medio en S1.1 (cambia números visibles), alto en S1.6/S1.7 (MV y
tabla núcleo): ambos con ventana y `plan` antes de `apply`.

### S2 — Ingesta

**Objetivo:** un solo camino de escritura (conectores), frescura por fuente
visible y ninguna pérdida de linaje.

Sin gate:

1. **Retirar el pipeline legacy de los caminos vivos.** `run_backfill_pipeline`
   y `dlq_retry` apuntan al bucle por meses de
   `_run_bulk_pipeline_connector` (`pipeline_runs.py:800-856`) parametrizado
   por mes de inicio; `scripts/backfill_documentos.py` se borra; en
   `scraper/pipeline.py` quedan solo `_ml_classify_entry`, `_load_classifiers`,
   `_summarize` y las constantes `INCLUSION_*`, que `connectors/placsp.py:64`
   importa. `process_month` y `backfill` se eliminan con sus tests, previa
   caracterización del bucle por conectores. Borrar tests requiere **[§6]**:
   pedir OK en el PR listando cuáles.
2. **Linaje que no se borra.** `_LIC_COALESCE_UPDATE_FIELDS` incorpora
   `inclusion_reason`, `filter_version`, `analysis_universe`, `fuente_origen`
   (los que existan como columnas de linaje). Test: re-ingesta de un expediente
   con `inclusion_reason='cpv_ti_universe'` desde un camino sin linaje lo
   conserva.
3. **Frescura por fuente.** `run_connector` ya escribe
   `source_ingestion_health`; el paso `healthcheck` gana un umbral por fuente
   (`SOURCE_MAX_LAG_HOURS` por conector, default 36 h para PLACSP, 7 días para
   RSS y TACRC) y emite `alert` si una fuente registrada no tiene run
   exitoso dentro del umbral. Las fuentes se registran en un inventario
   `scraper/connectors/__init__.py::REGISTERED_SOURCES` que
   `scripts/check_job_parity.py` cruza con los workflows.
4. **Docstring del chunking.** `db/upsert.py:813-815` deja de citar el write
   lock de SQLite: el motivo vigente es acotar tamaño de transacción y
   duración de locks en Postgres, y la no-atomicidad entre chunks queda
   escrita junto a la garantía que la cubre (`connectors/base.py:373-399`).

Ola 2:

5. **[§6 workflows, pre-autorizado D10] Saltos en verde.** En
   `scrape-daily.yml`, los pasos de PSCP y TACRC dejan de saltarse por
   `vars.X != ''`: corren siempre y el conector, si su variable está vacía,
   escribe `source_ingestion_health` con estado `disabled` y termina 0. Los
   seis `continue-on-error: true` se mantienen, pero cada conector escribe su
   resultado en `ops_events` (`connector_run`, con `status`) para que S2.3 lo
   vea.

**Verificación:** `make check`; `make job-parity`; un run de `scrape-daily`
con un conector forzado a fallar muestra la alerta por fuente y el job sigue
verde por el `continue-on-error`. **Riesgo:** medio (S2.1 toca el camino de
escritura; mitigado por los tests de caracterización previos).

### S3 — ML

**Objetivo:** que cada modelo tenga un canal de distribución real y que el
serving diga de dónde sale cada número.

Sin gate:

1. **[D2] Estado honesto de `ml_tecnologias`.** Hasta que D2 se cierre, el
   paso reporta `skipped` cuando no hay artefacto y `api/routes/feedback.py`
   expone el bloque de modelo como `unavailable` en vez de vacío. Si D2 es
   «publicar»: workflow `train-tech-model.yml` clonado de `train-model.yml`,
   con el gate de `services/ml/eval_tech.py` y el golden multi-etiqueta como
   bloqueante de promoción. **[§6 workflow]**: pedir OK.
2. **[D3] Un solo resolvedor de artefactos.** `api/model_cache.py` usa
   `resolve_active_artifact` (`services/ml/scoring.py:83-90`) con descarga a
   `tempfile.gettempdir()/tenderflow-models`; `ensure_downloaded` deja de ser
   una llamada exclusiva de `scraper/pipeline.py`. Test: activar una versión
   por `POST /models/{name}/activate/{version}` cambia el `model_version` que
   devuelve `/explain`.
3. **Origen del margen en el Radar.** `_load_margen_stats_raw` filtra por
   `model_version IS NOT NULL` o expone `origen ∈ {modelo, baseline}` por fila
   y `ScoringSignalsHealth.margen` distingue `ok_modelo` de `ok_baseline`; el
   job de scoring purga `predicciones_baja` de expedientes cerrados hace más de
   90 días (cierra el P3 del backlog «Vigilar el crecimiento»).
4. **Drift con una sola tabla de umbrales.** `_PSI_WARN`/`_PSI_CRIT` salen de
   `scheduler/drift_monitor.py` y `services/ml/drift.py` a
   `shared/scoring_weights.py` o módulo hermano; `drift_report.py` persiste
   el resumen en `ops_events` (`drift_report`, con el JSON de métricas) en
   vez de HTML en `data/reports/` del runner; tabla en `docs/sli-slo.md` con
   los seis mecanismos, su cadencia y su canal (S7 la enlaza).
5. **Cobertura de features nula.** `baja_model` descarta antes del ajuste las
   columnas sin ningún valor observado, con log y test (cierra el P2 del
   backlog «HistGradientBoosting revienta»).

**Verificación:** `make check`; `ml-scoring.yml` en verde con el log
`scoring_signals_margen_cargada` mostrando el desglose por origen.
**Riesgo:** bajo; S3.2 medio (toca lo que sirve la API).

### S4 — Backend

**Objetivo:** cerrar los tres bugs de datos, quitar el fail-open de tenencia y
que `api/app.py` vuelva a ser un composition root.

Sin gate:

1. **Un constructor de filtros.** `build_licitaciones_where`
   (`aggregates.py:159-228`) y `_base_filters`
   (`db/repositories/licitaciones.py:161-267`) convergen en un solo builder
   sobre SQLAlchemy Core (ADR-025) con la misma semántica de `q` (título,
   descripción, órgano, expediente, con plegado de acentos) y de `tecnologia`
   (explode del CSV, nunca igualdad); `adjudicaciones.py:180` lo adopta. Test
   de paridad: mismo filtro, mismo `COUNT(*)` en listado y en overview.
2. **`/analytics/competitors` acotado.** `load_for_competitors` recibe
   `limit` (default 5.000 filas) y el top-N por empresa se calcula en SQL; la
   resolución de identidad en pandas se aplica solo al top; el tripwire de
   `tests/test_api_startup.py` pasa a ser estructural: ningún método de
   `db/repositories/*` alcanzable desde `api/routes/analytics.py` devuelve
   `rows_to_dicts` sin `LIMIT` (escáner AST con allowlist vacía).
3. **Tenencia obligatoria.** `organization_id: int` deja de ser opcional en
   `db/repositories/watchlist.py`, `db/saved_filters.py`,
   `db/watchlist_empresas.py`, `db/repositories/user_profiles.py`,
   `db/notifications.py`; se borran las ramas `is None`; `add_item` sin
   organización es `TypeError`. Antes: consulta en producción de filas con
   `organization_id IS NULL` en esas tablas y, si las hay, script de
   asignación a la organización personal del `user_key` (sin migración: es
   UPDATE de datos, va en `scripts/` con `--dry-run`).
4. **`api/app.py` como composition root.** `_MaxBodyMiddleware`,
   `_RejectNulMiddleware` y `correlation_id_middleware` pasan a
   `api/middleware.py`; `/metrics` pasa a `api/routes/metrics.py` con
   `Depends(require_scope("metrics:read"))` y desaparece la validación
   inline de API key.
5. **Whitelist TID251 −4.** `api/routes/empresas.py`, `eventos.py`,
   `watchlist_rules.py` (y `exports.py`, ya en O0.8) mueven su SQL a `db/`;
   `pyproject.toml` pierde las cuatro entradas; `make status` regenera.
6. **[D8] CSRF único.** `_sign_session`/`_verify_session` de
   `api/routes/auth.py:124-159` se borran con su test **[§6 borrar tests:
   pedir OK]**; `dual_auth.py:64-69` llama a la misma función que
   `auth.py:313-316`. Si D8 es «adoptar», RFC breve y migración de formato
   con periodo de gracia (aceptar ambos durante una rotación de `SIGNING_KEY`).
7. **`shared/dto.py` dice la verdad.** Se borran `LicitacionSummary`,
   `LicitacionDetail`, `AdjudicacionSummary`, `ClusterSummary`,
   `KpiSnapshotDTO` de `shared/dto.py` (los vivos están en las rutas);
   `shared/__init__.py` y `tests/test_contract_dto.py` se ajustan; el
   docstring del módulo pasa a «tipos compartidos por más de una ruta».
   `make check-api-contract` y `codegen-drift` verifican que el esquema no
   cambia.
8. **Cachés.** `api/cache.py` (fachada de 57 líneas) se borra y sus dos
   consumidores usan `shared/cache.py`; se escribe en `docs/api-design.md`
   la tabla de las capas de caché que quedan, con quién invalida cada una
   tras una ingesta.

Ola 2:

9. **[D7] Export asíncrono.** Si «retirar»: RFC de contrato, los tres
   endpoints salen de `api/app.py:572` y del esquema, `check_openapi_contract`
   registra la retirada. Si «Redis»: `_store` pasa a `shared/cache.py` con
   namespace `exports` y TTL 900 s.
10. **Paginación común** (P2 del backlog ya abierto): `Paginated[T]` en
    `shared/dto.py` y adopción por olas; `trends` acota rango o expone `freq`.
11. **`aggregates.py` por dominio.** Tras S4.1, cada bloque cohesivo que se
    toque por otro motivo se extrae a `aggregates_<área>.py` (regla del P3
    del backlog «módulos-dios»); no big-bang.

**Verificación:** `make check`; `make check-api-contract`; `make fuzz-api`
en CI; test de paridad de S4.1 verde. **Riesgo:** medio en S4.1 y S4.3
(cambian resultados y rechazan llamadas); bajo el resto.

### S5 — Frontend

**Objetivo:** que el dashboard use lo que ya paga (RSC), que ninguna página sea
un componente de 600 líneas y que ninguna llamada esquive el cliente tipado.

Sin gate:

1. **Prefetch en servidor con hidratación.** Patrón de referencia en
   `resumen` y `radar`: el `page.tsx` servidor hace `prefetchQuery` con el
   cliente de servidor y envuelve en `HydrationBoundary`; `force-dynamic` se
   conserva en el layout (privacidad) pero deja de ser la única razón del
   render. Documentar el patrón en `web/AGENTS.md` y extenderlo por olas.
2. **Cinco páginas monolito.** `mi-watchlist`, `detalle`, `radar`,
   `competidores`, `mi-perfil` e `investigador` reparten estado y mutaciones
   en `_hooks/use-<página>.ts` y presentación en `_components/`, siguiendo el
   patrón ya vigente en `mercado`, `ops`, `mi-pipeline` y `resumen`. Umbral:
   ningún `page.tsx` ni componente con más de 300 líneas; ESLint
   `max-lines` a 300 en `src/app/**` con la allowlist inicial de los que
   faltan, que solo encoge.
3. **[D6] Rutas muertas.** Borrar los 17 directorios de ruta que
   `legacyRedirects()` redirige; `mi-pipeline/page.tsx:33` y
   `competencia/page.tsx:25-26` importan componentes de `_components/`, no
   módulos `page`; `titulos-de-pagina.test.ts` deriva la lista de
   `console-spaces.ts` en vez de pinear rutas.
4. **Cliente único.** Los ~30 `fetch("/api/...")` crudos migran a `apiGet`,
   `apiMutate` o `fetchWithAuth`; regla ESLint `no-restricted-syntax` que
   prohíbe `fetch(` con literal `/api/` fuera de `src/lib/`. Cierra el P2 del
   backlog «Migrar las llamadas al cliente tipado».
5. **Query keys.** `src/lib/query-keys.ts` con fábricas por recurso; se
   resuelve la colisión de `["ask-models"]` (una sola `queryFn`, la tipada) y
   se deduplican `["watchlist-empresas"]`, `["documentos", id]`,
   `["feedback-stats"]`, `["webhooks"]`. ESLint: `@tanstack/eslint-plugin-query`
   con `exhaustive-deps`.
6. **[§6 deps, pre-autorizado D10] Peso muerto.** Borrar `sankey-chart.tsx`,
   `page-header.tsx` y sus tests (o darles un uso real en la misma PR);
   retirar las ocho dependencias `d3-*` y sus `@types`; decidir entre
   `DataTable` (react-table) y `TableVirtuoso`: `detalle` adopta la
   virtualización y `renovaciones` el `DataTable`, y la librería que quede
   sin uso se retira. Añadir `@next/bundle-analyzer` con un informe en el PR.
7. **Un vocabulario de superficie.** `components/ui/card.tsx` queda marcado
   `@deprecated` a favor de `components/console/panel.tsx`; regla ESLint que
   prohíbe importar `ui/card` desde ficheros nuevos (allowlist de los 45
   actuales, que solo encoge).
8. **Tests donde toca.** Los tests de `components/__tests__/` que prueban
   `ui/`, `charts/` y `layout/` se mueven junto a su componente;
   `vitest.config.ts` gana un piso para `src/app/**` al valor medido y
   elimina la línea de `src/middleware.ts`; `accessibility.spec.ts` añade las
   rutas públicas (`/`, `/licitaciones`, `/cpv`, una ficha) y una ruta más del
   dashboard por PR; la lista `disableRules` solo encoge (empezar por
   `nested-interactive`, P2 ya abierto).
9. **Toaster y providers en un sitio.** Un `app/(app)/layout.tsx` intermedio
   que monte `Providers` y `Toaster` una vez para dashboard, login y
   restablecer contraseña, manteniendo la superficie pública fuera.

**Verificación:** `make web-lint`, `make web-typecheck`, `make web-test`
(con `--pool=threads --no-file-parallelism` en esta máquina),
`make check-frontend-invariants`, E2E en CI. **Riesgo:** medio en S5.1 y
S5.3 (routing y datos iniciales); bajo el resto.

### S6 — Plataforma

**Objetivo:** que el repo sepa cómo está desplegado, que un humano se entere de
un incidente y que el runtime no tenga privilegios de schema.

Sin gate (más allá de lo pre-autorizado en D10):

1. **[D4] Render verificado.** Acción del mantenedor: comprobar en el
   dashboard Blueprint, `autoDeploy`, `healthCheckPath` y plan; anotar el
   resultado y la fecha en la cabecera de `render.yaml`. Si se replica a
   mano, el fichero pasa a decir «documental: el dashboard manda» en su
   primera línea.
2. **Schema aplicado = cabeza del repo.** `/health/ready` compara
   `alembic_version` con `ScriptDirectory.get_heads()` (import diferido de
   alembic, ya es dependencia) y devuelve `degraded` con
   `schema: behind(v97 < v98)` si difieren; `deploy.yml` y `smoke.yml` fallan
   ante ese estado; `migrate.yml` conserva `workflow_dispatch` pero gana un
   job `plan` automático en cada push a master que comenta el diff pendiente
   en el commit (solo lectura). **[§6 workflows]** pre-autorizado en D10.
3. **[D5] Alertas que llegan.** Si Alertmanager: `pserv` en `render.yaml`
   construido desde `docker/Dockerfile.alertmanager`, `alerting:` en
   `prometheus.render.yml`, receptor email más un segundo canal (webhook
   de Slack o similar; el mantenedor elige), y una regla `Watchdog` que dispara
   siempre para detectar el silencio del propio canal. `observability/alerts.py`
   gana `alert_delivery_failed_total` y el healthcheck lo vigila.
   `ALERT_EMAIL_TO` y `ALERT_SMTP_*` pasan a los 14 workflows que hoy no los
   reciben, en particular `pliegos.yml`, `smoke.yml` y `security.yml`.
4. **Mínimo privilegio en BD.** Acción del mantenedor con acompañamiento:
   ejecutar `scripts/setup_pg_roles.sql`, crear `DATABASE_ADMIN_URL` solo
   para `migrate.yml`, rotar `DATABASE_URL` al rol `tenderflow_app`, y
   confirmar con `psql` que el runtime no puede DDL y que la RLS deja de ser
   inerte. `config/settings.py` gana `DATABASE_ADMIN_URL` documentada en
   `.env.example` **[§6 .env.example: pedir OK]**.
5. **[D9] CI más barato.** Job `setup` que cachea `pip` y `npm` y publica el
   build de Next como artefacto para `frontend-e2e`; matriz 3.12 fuera del
   PR; `check_coverage_per_module.py` cableado en `static-analysis`;
   `addopts` de `pyproject.toml` sin `--cov` (la cobertura la pide CI);
   `pliegos.yml` instala `[ml-embeddings]` una sola vez con caché de pip.
6. **Variables que no pisan defaults.** En todos los workflows, el idioma
   `X: ${{ vars.X || 'literal' }}` se sustituye por un paso que exporta la
   variable **solo si está definida** (`if [ -n "${{ vars.X }}" ]; then echo
   "X=..." >> $GITHUB_ENV; fi`), de forma que el default vigente sea siempre
   el de `config/settings.py`. Test: `scripts/check_env_parity.py` falla ante
   cualquier `|| '` en un bloque `env:` de workflow.
7. **Imagen de la API.** `.dockerignore` (O0.10) más `pip` actualizado (O0.4)
   más medición del tamaño de imagen en el job `docker-build` con umbral que
   solo baja.

**Verificación:** `make check-env-parity`, `make job-parity`; un deploy con
schema atrasado provocado a propósito en preview falla en `deploy.yml`; la
regla `Watchdog` llega al receptor. **Riesgo:** medio (S6.2 y S6.4 tocan
producción; ventana y `plan` primero).

### S7 — Documentación y decisiones

**Objetivo:** que ningún doc contradiga el código y que las decisiones nuevas
tengan ADR.

1. **ADR-026 — Caminos de lectura analítica y precedencia de tecnología.**
   Redibuja el diagrama de ADR-023 con los cinco caminos (SQL en vivo, SQL +
   pandas acotado, `kpi_snapshots`, `mat_clusters`, `licitaciones_canonicas`,
   DuckDB/Parquet), el contrato de frescura de cada uno y la regla de
   precedencia de S1.6. Marca ADR-023 como superseded en esa parte.
2. **Runbooks.** `disaster-recovery.md` deja de describir SQLite y enlaza al
   procedimiento Postgres vigente (sin tocar backup/restore, fuera de
   alcance); `observability-alerts.md` describe el plano real tras S6.3;
   `rate-limit-reset.md` y `dlq-replay.md` se re-verifican contra el código y
   llevan fecha de verificación en cabecera.
3. ~~**Un solo árbol de decisiones.**~~ **RETIRADO el 2026-09-03: la premisa era
   falsa.** El diagnóstico dio `docs/adr/discussions/` por «dos copias paralelas
   de las mismas decisiones» porque comparte numeración con `docs/rfc/`. No lo
   es: ambos se numeran por issue de GitHub, pero el RFC es la **decisión** y
   `discussions/` es el **log de deliberación** que la produjo. Su propio README
   lo declara archivo append-only, da la clave de lectura (los turnos
   `agent:<rol>` del esquema multi-rol retirado el 2026-07-30) y avisa de que
   varias entradas se citan desde ADRs y RFCs vivos. Fusionarlas habría
   destruido contexto para ahorrar ficheros. Lo que sí queda es que
   `docs/rfc/README.md` presenta como vigente el rol `agent:architect`, que ya
   no existe: se corrige en S7.4.
4. **Cabeceras de verdad.** `render.yaml` (tras S6.1), `docker/Dockerfile.web`
   («solo compose local; producción es Vercel») y `scraper/pipeline.py`
   (tras S2.1, o borrado).
5. **Backlog.** Cada stream mueve sus ítems a Cerrados al mergear; los que
   este plan cubre y ya están abiertos (`HistGradientBoosting`, `render.yaml`,
   `requirements` separados, `Cobertura frontend`, `axe`, `Migrar llamadas al
   cliente tipado`, `Contrato de paginación`, `módulos-dios`, `Calientes`,
   `predicciones_baja`, `Dependabot fantasma`) llevan una nota con el stream
   que los cierra para que nadie los trabaje en paralelo.

**Verificación:** `make check-agent-docs`; enlaces de docs no rotos.
**Riesgo:** nulo.

---

## 6. Métricas de cierre del plan

Se consideran cumplidas cuando `make status` y los comandos indicados las
reproducen; no se anotan cifras a mano en este fichero.

| Métrica | Hoy (2026-09-02) | Objetivo | Cómo medir |
|---|---|---|---|
| Workflows programados en rojo | 4 (`scrape-daily`, `train-predictivos`, `security`, más backup/restore fuera de alcance) | 0 salvo los excluidos | `gh run list --status failure` |
| Copias literales del predicado de universo fuera de `db/sql_fragments.py` | ~25 | 0 | escáner de S1.2 |
| Whitelist TID251 | 32 | ≤ 24 | `make status` |
| Escritores de `licitaciones` fuera de `scraper/connectors/` | 2 (`pipeline.py`, `dlq_retry`) | 0 | grep `upsert_licitaciones(` |
| `fetch("/api/` crudos en `web/src` fuera de `lib/` | ~30 | 0 | regla ESLint de S5.4 |
| `page.tsx` o componente > 300 líneas | 6 | 0 | `max-lines` de S5.2 |
| Rutas del dashboard redirigidas y aún compiladas | 17 | 0 | `legacyRedirects()` vs `git ls-files` |
| Reglas de Prometheus sin receptor | 9 | 0 | `alerting:` en `prometheus.render.yml` |
| Revisión aplicada en prod ≠ cabeza del repo sin que nada lo detecte | sí | no | `/health/ready` de S6.2 |

## 6bis. Seguimiento obligatorio DESPUÉS de aplicar las migraciones

Estos cambios están deliberadamente **desconectados** en el código porque
aplicarlos antes de que la migración esté en producción rompería la ingesta.
Cada uno solo puede aterrizar cuando `migrate.yml` haya aplicado su revisión.

### F1 — `db/upsert.py` debe escribir `primera_extraccion`, y solo en el INSERT

`v100` crea la columna y la rellena, y `db/sql_fragments.py` ya la prefiere.
Pero **el upsert no la conoce**, así que toda fila nueva la trae a `NULL`. Eso
es seguro —los fragmentos conservan `fecha_extraccion` como último término del
`coalesce`, o sea que una fila con la columna vacía se comporta exactamente
como antes—, pero significa que el beneficio hoy solo lo tiene el histórico ya
rellenado: **las filas nuevas siguen con la clave canónica móvil**.

No se cableó ahora por una razón concreta: `_LIC_KEYS` sale de
`fields(Licitacion)`, así que añadir el campo al dataclass cambia la lista de
columnas del `INSERT`. Producción está en `v97`. Si ese código llega antes que
la migración, **todas las escrituras del scraper fallan** con
`column "primera_extraccion" does not exist` — es decir, la ingesta entera cae,
que es justo la clase de incidente que `migrate.yml` existe para evitar y que
S6.2 vigila.

`tests/test_s2_linaje_coalesce.py` deja puesto el disparador: afirma que la
columna **no** está en el dataclass y que `_LIC_INSERT_ONLY_FIELDS` está vacío,
con el mensaje que dice qué hacer. El día que alguien la añada sin declararla
como insert-only, el test falla en vez de que la clave vuelva a moverse en
silencio.

**Cuándo hacerlo:** con `v100` aplicada y verificada en producción. Entonces:
añadir `primera_extraccion` al dataclass, añadirla a `_LIC_INSERT_ONLY_FIELDS`
(el mecanismo ya existe y `_LIC_UPDATES` ya la excluiría del `ON CONFLICT DO
UPDATE`), rellenarla en el upsert con el valor de `fecha_extraccion` cuando
venga vacía, y actualizar ese test.

### F2 — medir el delta de las cifras que cambian

Dos cambios mueven números visibles y **ninguno se ha medido**, porque esta
sesión no tiene Postgres:

- **S1.1**: `kpi_snapshots` pasa del universo estrecho al ancho. Los KPIs
  precalculados van a cambiar de valor. Es una corrección, no una regresión,
  pero series anteriores y posteriores no son comparables sin decirlo.
- **S1.6 (`v99`)**: el universo publicable admite la señal de ML/LLM/pliego, así
  que la superficie pública **crece**. Es el objetivo, y hay que comprobar que
  lo que entra es tecnología de verdad y no ruido del clasificador.

Comando: `make audit-truth-check` contra BD real antes y después, anotando el
delta. Si el crecimiento de S1.6 mete ruido, el umbral que lo gobierna es
`PLIEGO_TECH_MIN_SCORE`.

### F3 — la vista materializada no se entera de los cambios de código

Recordatorio que ya cuesta un incidente cada vez que se olvida: una vista
materializada **congela su consulta al crearse**, y `REFRESH` no relee el
código. Cualquier cambio futuro de `_publicable_sql` o de
`universo_tecnologico_sql` exige una revisión Alembic nueva que reconstruya
`licitaciones_canonicas`, con la permuta construir-al-lado → `DROP` + `RENAME`.
Está en ADR-026 §A.

---

## 8. Estado de implementación (2026-09-04)

Implementado en la rama `claude/arq-2026-09` (base `origin/master` = `1a4f094`).
La ejecución la hicieron agentes en paralelo; **tres murieron a la vez por
límite de sesión**, así que hay ítems a medias y están marcados como tales. Un
ítem sin verificar no se marca hecho.

### Controles ejecutados sobre el árbol final

| Control | Resultado |
|---|---|
| `ruff check` | verde (805 ficheros formateados) |
| `mypy` strict | **verde, 758 ficheros, cero errores** |
| Suite unitaria (`-m unit`) | **2779 pasan, 1 skip, 0 fallan** |
| 6 gates del repo (agent-docs, env-parity, job-parity, frontend-invariants, public-surface, requirements-sync) | los 6 verdes |
| Contrato OpenAPI (`check_openapi_contract`) | verde — **0 operaciones opacas, allowlist en 0** |
| `gen_status --check` | sincronizado |
| `alembic heads` | una sola cabeza (`v102`) |
| Frontend `tsc --noEmit` | **0 errores** |
| Frontend `eslint` | **0 errores** (7 avisos preexistentes de `window.location.href`) |
| Frontend `vitest` | **147 ficheros, 1690 tests, 0 fallan** |

**No ejecutado, y por tanto NO verde:** los tests de integración y E2E. Esta
máquina no tiene Postgres, y el E2E de Playwright además necesita backend y
build de producción. Todo lo que toca SQL nuevo se validó por la forma de la
query, no ejecutándola. **Las cuatro migraciones nuevas no se han aplicado
contra ninguna base de datos real.**

### Hecho

- **Ola 0** completa salvo lo que es acción humana: severidad por paso en el
  cierre (O0.2), retrain de predictivos (O0.3), verde en `security.yml` (O0.4),
  `ml_scoring` sin depender del disco del runner (O0.6), CSRF en el borrado de
  cuenta (O0.7), calendario ICS con ámbito de organización (O0.8) e higiene de
  `.gitignore`/`.dockerignore` (O0.10). O0.5 lo cerró otra sesión en `#260`.
- **S1** entero, incluidas las cuatro migraciones `v99`–`v102`.
- **S2** entero: el pipeline legacy sale de los caminos vivos, el linaje deja de
  borrarse en re-ingesta, y hay frescura por fuente.
- **S3** entero.
- **S4** salvo el contrato de paginación (S4.10). El ratchet TID251 baja de 32 a
  28 y el de homónimos de DTO queda **en cero**.
- **S6** entero salvo lo que exige tocar infraestructura real.
- **S7**: ADR-026, runbook de alertas, `sli-slo.md`, `rfc/README.md` y este
  documento.

### No hecho, y por qué

| Ítem | Estado |
|---|---|
| **S5.1** prefetch en servidor con hidratación | No empezado. El agente murió antes. |
| **S5.2** partir las páginas monolito | **A medias y revertido.** Se extrajeron hooks de `mi-watchlist` y `detalle`, pero el agente murió antes de recablear las páginas, dejando hooks huérfanos y el árbol en un estado incoherente. Se restauró al último estado bueno; el trabajo parcial está apartado, no perdido. Sin él, `max-lines` tampoco se puso. |
| **S5.9** grupo de rutas `(privado)` | **Revertido a conciencia.** El agente reescribió 9 imports de test a `@/app/(privado)/…` y murió antes de mover los directorios, dejando el árbol roto. Mueve TODA la superficie autenticada y no se puede verificar sin E2E, y el repo ya revirtió una vez un cambio de este tipo por heredarlo la superficie pública. Se revirtieron los imports. |
| **S4.10** paginación común | No empezado. |
| **S5.8** piso de cobertura de `src/app/**` y axe sobre la superficie pública | No hecho. Sí se movieron los 17 tests a la carpeta de su componente. |
| **O0.1 / O0.9 / S6.1 / S6.4** | Acción humana: aplicar migraciones, limpiar worktrees, verificar el panel de Render, cutover de roles de BD. |

### Sorpresas que corrigieron el plan

El plan se escribió desde un diagnóstico, y ejecutarlo desmintió cuatro cosas.
Quedan escritas porque un plan que no registra sus errores los repite:

1. **`docs/adr/discussions/` no duplicaba los RFC.** Es un log de deliberación
   archivado a propósito. El ítem se retiró (§5, S7.3).
2. **`licitaciones_history` no tiene columna `fecha_extraccion`.** El backfill de
   `v100` usa `LEAST(fecha_extraccion, MIN(captured_at))`, que es una cota
   superior honesta, y lo dice en su docstring.
3. **`competidores/` no se podía borrar entero.** Su subruta
   `empresa/[empresaId]` está viva y la enlazan dos componentes. Se podó solo la
   ruta muerta.
4. **`react-virtuoso` no era peso muerto.** Su consumidor no se borraba: se
   movía. La dependencia se queda.

Y un hallazgo que no venía en el diagnóstico: la regla ESLint que prohíbe
`fetch("/api/…")` llevaba las barras sin escapar en su selector, así que
`eslint` **reventaba con exit 2** en todo el frontend. Era un gate roto, no un
gate en rojo.

---

## 7. Lo que NO se toca

Verificado como sano en el diagnóstico; ningún stream lo refactoriza por
estilo: `db/connection.py` y los pools (ADR-025), el gate de promoción de
`services/ml/promotion.py`, `scripts/check_job_parity.py`, los jobs de
migraciones online de `ci.yml`, `web/src/lib/publico-api.ts`, el ratchet de
`scripts/check_openapi_contract.py` en cero, y la estructura de
`db/sql_fragments.py` (S1 lo completa, no lo reescribe).
