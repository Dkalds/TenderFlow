# Improvement Backlog

Lista viva de mejoras conocidas, priorizadas. **Diseñada para que un agente pueda elegir un ítem y trabajarlo sin pedir contexto extra al usuario.**

## Convenciones

- **Prioridad**: P0 (urgente / bloquea) · P1 (alta) · P2 (media) · P3 (nice-to-have).
- **Riesgo**: bajo (cambio aislado) · medio (afecta varios módulos) · alto (toca core / migra schema / cambia contrato).
- Si añadís un ítem nuevo, copiá la plantilla del final.
- Al cerrarlo, no lo dejes tachado aquí: **movélo entero a la sección _Cerrados_** del final con la fecha y el commit/PR que lo resolvió. Las secciones P1/P2/P3 contienen **solo ítems abiertos**.

---

## P1 — Alta

### [P2] Surface `participaciones_ute` en el frontend de competidores
- **Área:** web/src/components/competitors/company-profile-types.ts, web/src/components/competitors/company-profile-summary.tsx, web/src/app/(dashboard)/competidores/page.tsx
- **Problema:** el backend ya expone `participaciones_ute` en `GET /api/v1/competitive/.../perfil` (ver _Cerrados_, commit `33d98e4`) — por cada UTE de la que la empresa es miembro, sus `contratos`/`importe_total` propios y los `otros_miembros`. `company-profile-types.ts` todavía no declara el campo (compara con `por_cpv`/`por_anio`/`movimientos`, todas ya tipadas ahí) y ningún componente lo renderiza, así que el dato es invisible en la UI aunque ya viaja en la respuesta.
- **Acceptance criteria:** tipo `CompanyUteParticipation` en `company-profile-types.ts` reflejando el DTO; una sección en el dossier (`company-profile-summary.tsx` o vecino) listando las UTEs con sus `otros_miembros`, dejando claro que esos importes son **adicionales** a los totales directos de la empresa, no una desagregación de ellos (evitar que el usuario los sume dos veces mentalmente).
- **Riesgo:** bajo — solo lectura de un campo ya validado por el contrato OpenAPI/TS; sin cambio de backend.

### [P2] Mejorar el ranking de retrieval de producción (MRR 0.689)
- **Área:** db/search_backend.py, services/licitaciones.py
- **Problema:** Medido al migrar el eval RAG al motor real (ADR-018) sobre el golden set de 15 preguntas: SQLite/FTS5 da MRR ≈0.78 y Postgres/`tsvector`+`ts_rank_cd` da **0.689**. El `hit_rate@5` es **1.000 en ambos** — producción encuentra siempre el documento esperado dentro del top-5, pero lo ordena peor. No es una regresión de la migración: es la calidad real que ven los usuarios de `/ask` hoy, que nadie medía porque el eval corría sobre FTS5. El eval ratchea en `MRR_MIN = 0.65` (`tests/eval/test_eval_rag.py`), así que una regresión adicional salta. Con SQLite retirado (ADR-021) ya no hay comparación entre motores: 0.75 es el objetivo, no una paridad.
- **Acceptance criteria:**
  - MRR ≥ 0.75, subiendo `MRR_MIN` al valor alcanzado.
  - Vías a explorar: pesos por campo en el `tsvector` (`setweight` para dar más peso a `titulo` que a `descripcion`), `ts_rank_cd` con normalización distinta, o combinar con similitud `pg_trgm`.
- **Files de partida:** [db/search_backend.py](../db/search_backend.py), [tests/eval/test_eval_rag.py](../tests/eval/test_eval_rag.py)
- **Riesgo:** bajo — el eval con golden set actúa de red; cualquier cambio se mide antes de mergear.

### [P2] Verificar que el fix de PSCP progresa en producción tras el próximo deploy
- **Área:** scraper/connectors/pscp.py, observability
- **Problema:** El fix del cursor PSCP (ver Cerrados) es correcto y verificado con tests, pero corre contra un cursor YA atascado en producción desde hace semanas (`last_seen_updated='2026-06-19'`, sin `last_entry_id`). El primer run post-deploy re-consultará desde ese mismo punto (comportamiento esperado y correcto), pero hay que confirmar en los logs de Actions que el cursor **avanza** en el run siguiente (antes se quedaba pegado indefinidamente). Además, dado el volumen de filas que comparten el `:updated_at` de la republicación masiva (~1.86M filas), el conector tardará muchos ciclos en ponerse al día — el throughput por-registro (~240ms, probablemente dominado por round-trips US↔EU a Supabase) es una preocupación separada, no resuelta por este fix. **Actualización 2026-07-27:** el throughput sí está resuelto — la ruta de escritura pasó de un round trip por fila a `executemany` (ver _Cerrados_: 2201 → 6 viajes por lote de 800 filas). Queda solo la verificación en logs de que el cursor avanza.
- **Acceptance criteria:**
  - `gh run view <run> --log | grep pscp_fetch_start` muestra un `since` que avanza run a run (no repite el mismo timestamp).
  - ~~Si el throughput sigue siendo insuficiente, batchear los upserts para reducir round-trips por registro.~~ **Hecho 2026-07-27.** Si aun así no se pone al día, el siguiente eje es la co-locación del plano de ingesta con la BD (runners US vs Supabase EU), que contradice ADR-012 y requiere ADR nueva.
- **Files de partida:** [scraper/connectors/pscp.py](../scraper/connectors/pscp.py), [.github/workflows/scrape-daily.yml](../.github/workflows/scrape-daily.yml)
- **Riesgo:** bajo — solo observación; la acción de subir el timeout del step si hiciera falta requeriría gate humano.

### [P1] Verificar checklist F3d post-cutover (hardening Supabase) — solo acciones manuales pendientes
- **Área:** docs/runbooks, GitHub Settings, Supabase Dashboard
- **Problema:** El cutover F3c a Supabase Postgres ya se ejecutó. Todo el trabajo de **código y tooling** del hardening post-cutover está cerrado (ver progreso abajo); lo que queda es estrictamente **ejecución manual contra infraestructura real** con credenciales que un agente no tiene (gate secrets+ops, AGENTS.md §6).
- **Acceptance criteria (todas acciones del usuario — checklist ejecutable en el runbook):**
  - `BACKUP_ENCRYPTION_KEY` generado y cargado como GH Secret.
  - Password del rol dueño rotada; `DATABASE_URL` reconstruida con `sslmode=verify-full`.
  - `DATABASE_ADMIN_URL` (rol dueño, solo para alembic) guardada como secret aparte.
  - `scripts/setup_pg_roles.sql` ejecutado contra Supabase; `DATABASE_URL` de runtime apuntando al rol `tenderflow_app`; verificado que puede DML pero no DDL.
  - Confirmado (`psql`) que `v52_rls_lockdown` está aplicada y `has_table_privilege('anon',…)` es false.
  - ~~Turso retirado una vez pasada la ventana de rollback ≥14 días.~~ **Hecho 2026-07-26 (ADR-020)** — pendiente solo la acción manual de revocar el token en el dashboard de Turso y borrar los GH Secrets `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN` (código y workflows ya no los usan).
- **Files de partida:** [docs/runbooks/migracion-persistencia.md](runbooks/migracion-persistencia.md) (Paso 9, checklist ejecutable), [docs/runbooks/backup-restore.md](runbooks/backup-restore.md), [scripts/setup_pg_roles.sql](../scripts/setup_pg_roles.sql)
- **Progreso 2026-07-13 (plan Pliegos+RAG, fases D1/D2 — CERRADAS del lado de código):**
  - `docs/runbooks/backup-restore.md`: sección "Backups Postgres cifrados" (alta del secret, verificación, descifrado, restore).
  - `scripts/setup_pg_roles.sql`: rol `tenderflow_app` (solo DML + timeouts) + políticas RLS explícitas por tabla (`tenderflow_app_full_access`) que resuelven la dependencia con `v52_rls_lockdown` (rol no-dueño + RLS sin políticas = deny-all).
  - `config/settings.py::_validate_prod_database_ssl`: ahora exige `sslmode` seguro para **cualquier host remoto, independientemente de `ENV`** (antes solo en prod/staging) — cierra el gap real donde `scrape-daily.yml` corre con `ENV=dev` contra Supabase sin que el validator actuara. Host local (`localhost`/`127.0.0.1`/`::1`) sigue exento (sin red externa que interceptar). 4 tests nuevos en `test_config_settings.py` cubren la matriz ENV×host×sslmode.
  - `docs/runbooks/migracion-persistencia.md` Paso 9 reescrito como checklist `- [ ]` ejecutable con comandos psql concretos.
  - 2026-07-26: `setup_pg_roles.sql` endurece el rol de runtime con `NOINHERIT`/`NOBYPASSRLS` y sin `CREATE` en `public`; Alembic v59 revoca `EXECUTE` público sobre la función `SECURITY DEFINER` de RLS. Sigue pendiente ejecutar el checklist contra Supabase.
- **Riesgo:** bajo — todo el código/tooling es aditivo y ya está testeado; el riesgo real pendiente es que el usuario no ejecute el checklist (backups sin cifrar, credencial sin rotar, rol de privilegios mínimos sin crear).

### [P1] LLM como dependencia gestionada (presupuesto + circuit-breaker + fallback + eval RAG)
- **Área:** llm/, api/routes/ask.py, observability
- **Problema:** `/ask` es ahora un camino de producción con proveedor externo de pago (NVIDIA NIM/DeepSeek, commit `d6619f8`). El RFC de tokens (`implemented`) cerró la *medición* y dejó el *enforcement* para "un RFC posterior". Falta: presupuesto/circuit-breaker de gasto, fallback degradado si el proveedor cae, y eval de RAG (sin eval set las regresiones de calidad son invisibles a CI). Este es ese RFC posterior.
- **Acceptance criteria:**
  - Con presupuesto superado y `LLM_BUDGET_MODE=enforce`, `/ask` responde 429/503 sin llamar al proveedor; `llm_budget_exceeded_total` sube. Modo `monitor` solo alerta.
  - Ante fallo del proveedor o breaker abierto, `/ask` degrada a documentos del RAG sin síntesis (`degraded` en el stream); el SSE no rompe y el DTO no cambia (§3.5).
  - Eval de **recuperación** determinista en CI (sin LLM real) que falla si se rompe el contexto recuperado.
- **Files de partida:** [api/routes/ask.py](../api/routes/ask.py), [llm/client.py](../llm/client.py), [config/settings.py](../config/settings.py), [docs/adr/[[ADR-006-etag-pdf-export-ratelimit-redis|ADR-006]]-etag-pdf-export-ratelimit-redis.md](../docs/adr/ADR-006-etag-pdf-export-ratelimit-redis.md)
- **RFC:** [2026-06-30-rfc-llm-dependencia-gestionada.md](rfc/2026-06-30-rfc-llm-dependencia-gestionada.md)
- **Riesgo:** medio — toca un endpoint de producción; mitigado por `LLM_BUDGET_MODE=monitor` como default (medir antes de cortar) y contrato API intacto. **Construye sobre** el RFC de observabilidad de tokens (P2, abajo).

---

## P2 — Media

### [P2] Calibrar los umbrales de la auditoría de verdad del dato
- **Área:** scripts/audit_domain_truth.py
- **Problema:** `MAX_PCT_SIN_FECHA_LIMITE = 60`, `MAX_PCT_FILAS_UTE = 8` y `MAX_DELTA_BAJA_PUNTOS = 5` se eligieron holgados para que el primer mes detecte empeoramientos bruscos sin ahogar en ruido. No son la calidad real medida.
- **Acceptance criteria:**
  - Tras una semana de ejecuciones de `.github/workflows/domain-truth.yml`, comparar los `domain-truth.json` archivados y bajar cada umbral al valor medido con margen, dejando el histórico en el docstring (patrón de `tests/eval/test_eval_rag.py`).
- **Files de partida:** [scripts/audit_domain_truth.py](../scripts/audit_domain_truth.py)
- **Riesgo:** bajo — solo umbrales.

### [P2] Persistir procedimiento, tramitación y criterios de adjudicación
- **Área:** scraper/codice_parser.py, db/alembic, services/ml/features.py
- **Problema:** el tipo de procedimiento (abierto/negociado/menor), la tramitación (ordinaria/urgente) y el **peso del precio en los criterios de adjudicación** no existen como columnas. Son los tres drivers más fuertes de la baja en contratación pública española, y el RFC de modelos predictivos ya los marcó como gap en junio de 2026 (§Restricciones de datos). Sin ellos, el modelo de baja tiene un techo que no se sube con más features derivadas: el saneamiento de agosto de 2026 agotó lo que se puede extraer de las columnas existentes.
- **Acceptance criteria:**
  - `parse_licitaciones` extrae los tres campos de `cac:TenderingProcess` / `cac:AwardingCriterion` (el parser ya lee `TenderSubmissionDeadlinePeriod` de ese mismo bloque, ver `scraper/codice_parser.py`).
  - Migración append-only con las columnas nuevas + backfill medido sobre los ZIP cacheados; se reporta el % de cobertura real por campo antes de usarlas como feature.
  - Entran en `FEATURE_COLUMNS` solo si la cobertura supera el 50%, y el reentrenamiento reporta el delta de `mae_p50` contra la versión previa.
- **Files de partida:** [scraper/codice_parser.py](../scraper/codice_parser.py), [services/ml/features.py](../services/ml/features.py), [db/repositories/ml_dataset.py](../db/repositories/ml_dataset.py)
- **Riesgo:** medio — toca parser, esquema y dataset de un modelo en producción; el guard de `feature_columns` de `BajaModel` degrada a baseline si se despliega el código sin reentrenar.

### [P2] Modelo de baja por lote
- **Área:** services/ml, db/alembic, api/routes/predicciones.py, web/
- **Problema:** el modelo predice la baja **agregada por expediente** porque es la granularidad que puede servir `predicciones_baja` (PK `licitacion_id`) y la que mide `services/ml/calibration.py`. Pero el lote es la unidad sobre la que realmente se puja: en un expediente de 30 lotes, una sola cifra agregada es menos accionable que 30.
- **Acceptance criteria:**
  - Migración de `predicciones_baja` a PK `(licitacion_id, lote_id)` con `lote_id` nullable para expedientes de lote único.
  - `db/repositories/ml_dataset.py` expone la variante por lote (el denominador por fila ya existe: `EFFECTIVE_BUDGET_SQL`), `calibration.py` compara a la misma granularidad, y el DTO/endpoint/frontend exponen el desglose.
  - Se compara `mae_p50` por lote contra el agregado actual antes de sustituirlo; si no mejora, se documenta y se queda el agregado.
- **Files de partida:** [db/repositories/ml_dataset.py](../db/repositories/ml_dataset.py), [services/ml/calibration.py](../services/ml/calibration.py), [api/routes/predicciones.py](../api/routes/predicciones.py)
- **Riesgo:** medio — migración de una tabla materializada + cambio de contrato API.

### [P2] Sustituir los fixtures sintéticos del corpus CODICE por expedientes reales
- **Área:** tests/fixtures/placsp/
- **Problema:** los once casos del corpus golden son estructuralmente fieles al CODICE pero escritos a mano: la sesión que los creó no tenía ZIP mensuales cacheados ni acceso al feed. El valor del corpus está en codificar variabilidad que nadie imaginó, y eso solo lo dan los datos reales.
- **Acceptance criteria:**
  - `ENV=dev python scripts/capture_placsp_fixtures.py --caso <caso>` sustituye cada fixture sintético por uno real, y `python -m tests.test_codice_parser_golden --update` regenera el golden con el diff revisado.
- **Files de partida:** [scripts/capture_placsp_fixtures.py](../scripts/capture_placsp_fixtures.py), [tests/fixtures/placsp/README.md](../tests/fixtures/placsp/README.md)
- **Riesgo:** bajo — solo tests.

### [P1] Cobertura de tests de las páginas del frontend
- **Área:** web/src/app (tests vitest)
- **Problema:** Con el denominador corregido el 2026-08-10 (antes se excluía `src/app/**` entero alegando que son Server Components, y 34 de 37 páginas son `"use client"`), la cobertura real del frontend es **40.2/30.4/37.5/41.6**, no el 68/63/68/70 que CI parecía exigir. Las páginas están al 0%: ahí vive la lógica de filtros, mutaciones y derivación, en ficheros de más de 1.000 líneas (`competidores` 1.047, `mi-watchlist` 1.044, `detalle` 1.015). Los pisos por carpeta de `lib`/`hooks`/`components` conservan la garantía anterior, pero el conjunto está descubierto.
- **Acceptance criteria:**
  - Tests de los 3 flujos críticos que siguen sin cubrir: filtros nuqs (`web/src/lib/filters.ts` ya cubierto; falta su uso desde las páginas), watchlist (`use-watchlist-items`), streaming SSE de `/ask` (`ask-stream.ts`).
  - Extraer a hooks testeables la lógica de las páginas de 1.000+ líneas, en vez de testear el árbol entero.
  - Subir los umbrales globales de `vitest.config.ts` conforme suba lo medido. **No bajar los pisos por carpeta.**
- **Files de partida:** [web/vitest.config.ts](../web/vitest.config.ts), [web/src/lib/ask-stream.ts](../web/src/lib/ask-stream.ts)
- **Riesgo:** bajo — solo añade tests.

### [P2] Extraer las vistas de `/ops` a componentes compartidos
- **Área:** web/src/app/(dashboard)/ops
- **Problema:** `ops/page.tsx:28-33` importa con `dynamic()` **seis `page.tsx` completos** (`observabilidad`, `calidad-datos`, `administracion`, `feature-flags`, `active-learning`, `webhooks`) y los renderiza como componentes. Esos módulos siguen existiendo además como rutas propias, así que cada uno tiene dos puntos de entrada y dos estados de URL, y Next no puede tratarlos como boundaries de ruta. Es la costura de la consolidación en espacios, materializada en código.
- **Acceptance criteria:**
  - El cuerpo de cada una pasa a `_components/<x>-view.tsx`; tanto la ruta como `/ops` consumen esa vista.
  - `ops/page.tsx` deja de importar ningún `page.tsx`.
- **Files de partida:** [web/src/app/(dashboard)/ops/page.tsx](<../web/src/app/(dashboard)/ops/page.tsx>)
- **Riesgo:** bajo-medio — mecánico pero toca seis páginas; hacerlo de una en una.

### [P3] Documentar `FRONTEND_URL` y `SENTRY_DSN` en `.env.example`
- **Área:** .env.example
- **Problema:** `render.yaml` las declara y `.env.example` no las documenta, así que no se pueden descubrir leyendo el fichero que existe para eso. `scripts/check_env_parity.py` las lleva anotadas en `_DOCUMENTACION_PENDIENTE` para no bloquear CI; esa lista solo puede encoger. No se arreglaron en el mismo cambio porque tocar `.env*` requiere OK explícito (AGENTS.md §6).
- **Acceptance criteria:** ambas documentadas con un comentario de una línea; entrada retirada de `_DOCUMENTACION_PENDIENTE`; `make check-env-parity` sigue verde.
- **Files de partida:** [.env.example](../.env.example), [scripts/check_env_parity.py](../scripts/check_env_parity.py)
- **Riesgo:** bajo — documentación.

---

## P3 — Nice to have

### [P3] Migrar los `title=` nativos restantes a `Tooltip`
- **Área:** web/src (celdas de tabla y textos truncados)
- **Nota:** este ítem estaba duplicado (había una segunda entrada, "Completar la migración de `title=` nativos a `ui/tooltip.tsx`", con el mismo alcance). Fusionados el 2026-08-10.
- **Problema:** quedan ~180 `title=` nativos. No se disparan con teclado, su timing no es controlable y su estilo no sigue el tema. `components/ui/tooltip.tsx` existe con la política de delay ya afinada (`docs/frontend-motion.md`). La primera pasada cubrió los controles icon-only y la Ola 1 de UX los de la cabecera; el resto son celdas de tabla y textos truncados informativos.
- **Acceptance criteria:** ningún `title=` sobre un elemento interactivo; en celdas y textos truncados, o `Tooltip` o texto visible.
- **Files de partida:** [docs/frontend-motion.md](frontend-motion.md) (sección Tooltip)
- **Riesgo:** bajo — mecánico, pero masivo: hacerlo por olas.

### [P3] Barrido de ortografía castellana en las cadenas visibles restantes
- **Área:** web/src (páginas)
- **Problema:** decenas de cadenas de UI sin tildes ("prediccion", "analisis", "Busqueda", "Ultimos"), y `...` donde corresponde `…`. La Ola 1 cubrió navegación, barra de filtros, TopNav, `es.json` y la meta description; falta el interior de las páginas. En un producto B2B español se lee como descuido, no como estilo.
- **Acceptance criteria:** sin cadenas de UI sin tilde en `web/src/app/**`; tests actualizados a la par (varios asertan sobre el texto). Ojo con `.codespell-ignore-words.txt`: al acentuar, algunas entradas dejan de hacer falta y conviene retirarlas.
- **Riesgo:** bajo — pero toca muchos tests; hacerlo por página.

### [P3] Migrar la resolución de identidad de `competitors.py` a SQL (union-find + unaccent)
- **Área:** services/analytics/competitors.py, db/repositories/adjudicaciones.py
- **Problema:** Tras mover `overview.py`/`tecnologias.py` a agregación SQL (commit `ab520da`), `competitors.py` quedó híbrido a propósito: sus filtros (fecha/tecnologia/estado/importe_min) ya se empujan a SQL, pero la resolución de identidad de empresa (`_prepare_company_identity`/`_connected_identity_keys`, un connected-components/union-find sobre 5 tokens de identidad por fila) sigue en pandas. Migrarla a SQL necesita `normalize_company`/`normalize_nif` en el motor (NFKD accent-fold + 12+ alternativas regex de sufijo legal), lo que requiere la extensión `unaccent` de Postgres — no habilitada hoy (solo `pg_trgm`/`vector` lo están), y habilitarla exige una migración Alembic (fuera de alcance sin OK humano, AGENTS.md §6).
- **Acceptance criteria:**
  - Extensión `unaccent` habilitada (migración Alembic, requiere confirmación humana).
  - Connected-components de identidad expresado como CTE recursiva en `db/repositories/adjudicaciones.py` (o módulo hermano), con paridad de resultado verificada contra los 17 tests existentes de `tests/test_analytics_competitors.py` (casos: grupo Deloitte curado, joins solo-por-NIF, exclusión de NIF placeholder).
  - `_apply_filters` (red de seguridad redundante añadida en la migración parcial) puede retirarse si el filtrado SQL cubre todos los casos que cubría.
- **Files de partida:** [services/analytics/competitors.py](../services/analytics/competitors.py), [services/normalization.py](../services/normalization.py), [db/repositories/adjudicaciones.py](../db/repositories/adjudicaciones.py), [tests/test_analytics_competitors.py](../tests/test_analytics_competitors.py)
- **Riesgo:** medio — toca una migración de schema (gate humano) y una query recursiva no trivial; mitigado por los 17 tests de caracterización ya existentes.

### [P3] Decidir el destino de los tests tautológicos encontrados al redistribuir los batches de coverage
- **Área:** tests/test_TODO_review_tautologico.py
- **Problema:** Al redistribuir `test_unit_coverage_batch*.py` (commit `96ec96f`) a ficheros por módulo, 3 tests resultaron tautológicos (afirman sobre un mock que el propio test configuró, o ejercitan una rama que nunca se dispara de verdad) y se movieron a `tests/test_TODO_review_tautologico.py` en vez de borrarse, porque borrar tests existentes requiere OK explícito (AGENTS.md §6): `test_protocol_stubs` (verifica `hasattr` sobre un `Protocol`, cierto por construcción), `test_argon2_verify_success` y `test_argon2_import_error` (parchean un símbolo que `verify_password` no usa por ese nombre — el mock es un no-op inerte en ambos).
- **Acceptance criteria:**
  - Revisión humana de los 3 tests: o se borran (confirmando que no aportan cobertura real), o se reescriben para ejercitar el comportamiento real que su nombre sugiere.
  - `tests/test_TODO_review_tautologico.py` desaparece (vacío) al resolverse.
- **Files de partida:** [tests/test_TODO_review_tautologico.py](../tests/test_TODO_review_tautologico.py)
- **Riesgo:** bajo — son 3 tests aislados; el único riesgo es decidir mal si alguno en realidad sí ejercitaba algo no obvio.

### [P3] F5: Refactor de repositories por olas (TID251 whitelist decreciente)
- **Área:** services/, scheduler/, api/routes/, scraper/, scripts/
- **Problema:** El ratchet TID251 tiene una whitelist que solo puede decrecer (conteo vigente: [STATUS.md](STATUS.md), generado por `make status`). **Destino fijado por [ADR-022](adr/ADR-022-frontera-de-persistencia.md)**: el SQL se mueve a `db/`, y `db/repositories/*` (clases) y `db/*.py` (funciones de módulo) son el mismo estrato — o sea que **no hay renombrado de por medio**, cada archivo va al módulo `db/` de su tabla en la forma que ya tenga. Antes de ADR-022 este ítem no tenía estado final declarado, que era el motivo real de que llevara meses parado: refactorizar hacia un destino indefinido produce un idioma más, no menos.
- **Baseline (medido 2026-07-30 sobre `pyproject.toml`):** services/ 18 · scheduler/ 9 · scripts/ 5 · api/ 4 · scraper/ 2 = **38 archivos** en whitelist, más los dos globs estructurales que no son deuda (`db/**` y `tests/*`, exentos por diseño). El "= 44 entradas" del baseline anterior no cuadraba con el desglose (que ya sumaba 40 contando los globs); la cifra de referencia es la de STATUS.md, que cuenta archivos.
- **Progreso 2026-08-10 — primera ola, 38 → 36:** `services/job_locks.py` entero pasa a `db/job_locks.py` (aprovechando que había que corregir su `release()`, que borraba locks ajenos) y el `SELECT 1` de `services/health.py` pasa a `db.connection.ping()`. El ratchet llevaba meses sin moverse; la lección de esta ola es que sale barato cuando se hace **al pasar por el módulo por otro motivo**, no como pasada dedicada. Siguientes candidatos por coste (conteo de `connect(`+`execute(`): `services/ml/calibration.py` (1), `services/entity_resolution.py` (1), `services/licitaciones.py` (2), `services/competitive/bajas.py` (2), `services/ml/features.py` (2), `services/ml/retencion_labels.py` (2).
- **Orden de olas:** services/ → api/ → scheduler/ → scripts/ (por densidad; `services/` es además el único que viola la capa de dominio de ADR-007)
- **Excepción declarada:** `services/sql_fragments.py` se queda — expone fragmentos SQL constantes pero no ejecuta nada (ADR-022 §3).
- **Acceptance criteria por ola:**
  - `make check` verde tras cada ola.
  - `ruff check --select TID251 --statistics .` monotónamente decreciente (anotar conteo en cada PR).
  - Tests de caracterización donde falten.
  - Estado final: whitelist vacía (`db/**` no la necesita: importar `connect` desde dentro de `db/` está permitido).
- **Files de partida:** `pyproject.toml` (whitelist TID251), `db/repositories/`
- **Riesgo:** medio — toca caminos de datos; mitigado por ratchet como gate y tests de caracterización previos a cada movimiento.

### [P3] Unificar la definición de "Calientes" (heurística de resumen vs banda de scoring)
- **Área:** services/analytics/resumen, services/analytics/pipeline, services/analytics/scoring
- **Problema:** `services/analytics/resumen.py::get_resumen_hoy` calcula "calientes" como `importe ≥ P75 AND estado activo AND en plazo` (heurística ad-hoc), mientras que el KPI "Calientes" nuevo de `/analytics/pipeline` (2026-07-20) usa la banda de scoring genérico (`score ≥ 75`, `services/analytics/scoring.py`). Son dos definiciones distintas de la misma palabra visibles en páginas contiguas (Resumen enlaza su "Calientes" a Pipeline & Alertas), lo que puede desconcertar si los números no coinciden.
- **Acceptance criteria:**
  - Una sola definición de "caliente" reutilizada por ambos endpoints (lo más simple: `resumen_hoy` adopta la banda de scoring, ya que es la señal más rica — importe/plazo/competencia/margen/afinidad/riesgo vs. solo importe).
  - Los números de "Calientes" coinciden entre `/resumen` y `/pipeline-alertas` para el mismo dataset.
- **Files de partida:** [services/analytics/resumen.py](../services/analytics/resumen.py), [services/analytics/pipeline.py](../services/analytics/pipeline.py), [services/analytics/scoring.py](../services/analytics/scoring.py)
- **Riesgo:** bajo — cambia un número visible en dos KPIs; sin migración de schema.

### [P3] Ordenar /renovaciones por score de oportunidad en el servidor
- **Área:** web/renovaciones, services/competitive/renovaciones
- **Problema:** La tabla trae `limit=1000` ordenado por `fecha_fin_efectiva ASC` y **reordena en cliente** por el score de oportunidad (`web/src/lib/opportunity-score.ts`: riesgo × importe × urgencia). Con más de 1000 contratos en la ventana, el "top de oportunidades" que ve el usuario es el top de las 1000 primeras por fecha de fin, no del dataset. Es un residuo acotado del ítem de KPIs ya cerrado (los KPIs sí son totales de servidor) y está anotado en la línea con `fdi-allow:large-limit`.
- **Acceptance criteria:**
  - El score se calcula en SQL y `proximas_renovaciones` acepta `order_by=score`, de modo que el top-N mostrado sea el top-N real.
  - Retirar el `fdi-allow:large-limit` de `renovaciones/page.tsx`.
- **Files de partida:** [services/competitive/renovaciones.py](../services/competitive/renovaciones.py), [web/src/lib/opportunity-score.ts](../web/src/lib/opportunity-score.ts), [web/src/app/(dashboard)/renovaciones/page.tsx](<../web/src/app/(dashboard)/renovaciones/page.tsx>)
- **Riesgo:** bajo — la fórmula ya está escrita y es determinista; portarla a SQL es mecánico y el eval es comparar ambos órdenes sobre el mismo dataset.

### [P3] Scroll edge effects en vez de divisores duros bajo el chrome flotante
- **Área:** web/components/layout (top-nav, kpi-bar, global-filter-bar)
- **Problema:** `TopNav`, `KpiBar` y `GlobalFilterBar` son `tf-glass` (translúcidos, `position: sticky`) y cada uno delimita con un `border-b border-border/70` fijo, en vez del "scroll edge effect" que pide apple-design §12: un fade/máscara de blur activado por scroll, solo donde el contenido realmente pasa por debajo del chrome flotante. Hallazgo F11 de la revisión de las skills de Emil Kowalski (2026-07-25); no bloqueante, es refinamiento visual.
- **Acceptance criteria:**
  - El borde duro se sustituye por una máscara/gradiente que aparece solo cuando hay contenido scrolleado debajo (p. ej. vía `IntersectionObserver` en un sentinel, o `scroll-driven animations` si el soporte de navegador lo permite).
  - Sin borde visible cuando el contenido está en el tope (`scrollY === 0`).
- **Files de partida:** [web/src/components/layout/top-nav.tsx](../web/src/components/layout/top-nav.tsx), [web/src/components/layout/kpi-bar.tsx](../web/src/components/layout/kpi-bar.tsx), [web/src/components/layout/global-filter-bar.tsx](../web/src/components/layout/global-filter-bar.tsx)
- **Riesgo:** bajo — puramente visual, sin tocar datos ni contratos.

### [P2] Contrato de paginación común para la API

- **Área:** api/routes/
- **Problema:** `PaginatedResponse` vive en 1 de los 30 módulos de rutas (`licitaciones.py`) sobre 146 endpoints, así que cada consumidor del cliente TS aprende una forma distinta de paginar. Revisado el 2026-08-10: los endpoints de analytics **no** son el problema que parecía —devuelven agregados acotados por la cardinalidad del `GROUP BY` (≤19 CCAA, ≤52 provincias, nº de códigos tech) y `competitors`/`organos` ya aceptan `limit`—. El caso real de crecimiento no acotado es `trends`, cuya serie escala con la **longitud del rango de fechas** (10 años ≈ 3.650 puntos), donde un `limit` por filas es la herramienta equivocada: lo que hay que acotar es el rango o la granularidad del roll-up.
- **Acceptance criteria:**
  - Un `Paginated[T]` (o dependencia `limit`/`offset` compartida) reutilizado por las rutas que devuelven listas, aplicado por olas.
  - `trends` acota rango o expone `freq` de roll-up; documentado en el DTO.
- **Files de partida:** [api/routes/licitaciones.py](../api/routes/licitaciones.py), [api/routes/analytics.py](../api/routes/analytics.py)
- **Riesgo:** bajo — aditivo si se hace con defaults generosos.

### [P2] Migrar las llamadas del frontend al cliente OpenAPI tipado

- **Área:** web/src (hooks, componentes y páginas)
- **Problema:** El 2026-08-10 se añadió `apiGet` (tipado contra el esquema generado) y se migraron los dos hooks que quedaban con interfaces a mano, pero las ~94 llamadas existentes siguen usando `fetchWithAuth`/`apiMutate` con URLs literales y un cast sin validación. Mientras esas llamadas no pasen por el esquema, el job `codegen-drift` de CI custodia un artefacto que no protege el código que lo consume.
- **Acceptance criteria:**
  - Las llamadas de ruta estática usan `apiGet`; las de ruta dinámica tipan el retorno con `@/lib/api-types`, nunca con una interfaz local.
  - Por olas y por carpeta (`hooks/` primero, que es donde se concentran).
- **Files de partida:** [web/src/lib/api-client.ts](../web/src/lib/api-client.ts), [web/src/lib/api-types.ts](../web/src/lib/api-types.ts)
- **Riesgo:** bajo — `make web-typecheck` es el guardián.

### [P2] Aislamiento de la suite: una base por sesión en vez de un schema por test

- **Área:** tests/conftest.py
- **Problema:** Cada uno de los 157 ficheros de test con BD crea un schema completo (~50 tablas + índices), cierra el pool y abre uno nuevo (TCP + handshake TLS) y luego hace `DROP SCHEMA CASCADE`. El cacheo del DDL entre workers ya está hecho y bien; el coste residual es lineal en número de tests y es el techo estructural de la velocidad de la suite.
- **Acceptance criteria:**
  - `CREATE DATABASE … TEMPLATE` una vez por sesión, o aislamiento por transacción con rollback para los tests que no hacen DDL.
  - Tiempo del job `test` de CI medido antes/después en el PR.
- **Files de partida:** [tests/conftest.py](../tests/conftest.py)
- **Riesgo:** medio — toca el aislamiento de toda la suite; un fallo aquí se manifiesta como tests que se contaminan entre sí.

### [P3] Partir los dos módulos-dios: `aggregates.py` y `settings.py`

- **Área:** db/repositories/aggregates.py, config/settings.py
- **Problema:** `db/repositories/aggregates.py` son 1.327 líneas y 55 funciones en una sola clase que concentra toda la analítica; `config/settings.py` son 946 líneas con 26 validadores en una clase plana que mezcla ejes ortogonales (BD, ML, LLM, auth, scraper, observabilidad) que ya están conceptualmente separados por `APP_PROFILE`. Son los dos ficheros que todo el mundo tiene que tocar, y donde se concentran los conflictos de merge. (`shared/dto.py`, en contraste, está sano: 620 líneas / 45 clases.)
- **Acceptance criteria:**
  - `AggregateRepository` partido por dominio (overview / geografía / competidores), **al pasar por cada dominio**, no en un big-bang.
  - `Settings` en submodelos anidados por eje, preservando los nombres de variables de entorno.
- **Files de partida:** [db/repositories/aggregates.py](../db/repositories/aggregates.py), [config/settings.py](../config/settings.py)
- **Riesgo:** medio — mucha superficie; mitigable haciéndolo por partes con la suite verde entre cada una.

### [P3] Entorno de staging y plan de la API

- **Área:** render.yaml, infraestructura (acción del usuario)
- **Problema:** `render.yaml` define tres servicios, todos en `frankfurt`, ninguno de staging: el primer entorno donde un cambio se ejecuta contra infraestructura real es producción. La API corre además en `plan: free`, con spin-down por inactividad y 512 MB — el mismo contenedor donde ya hubo un OOM. El nuevo `deploy.yml` verifica el deploy, pero verificar no sustituye a tener dónde probar.
- **Acceptance criteria (decisión del usuario, con coste asociado):**
  - Decidir si se sube el plan de `tenderflow-api` (elimina spin-down y el techo de memoria).
  - Decidir si se añade un servicio de staging apuntando a una BD de staging, y si `deploy.yml` despliega allí primero.
- **Files de partida:** [render.yaml](../render.yaml), [.github/workflows/deploy.yml](../.github/workflows/deploy.yml)
- **Riesgo:** bajo técnico, con coste económico — por eso es decisión del usuario.

---

## Cerrados

El histórico de ítems cerrados vive en
[docs/archive/IMPROVEMENT_BACKLOG_CERRADOS.md](archive/IMPROVEMENT_BACKLOG_CERRADOS.md).
Al cerrar un ítem, movelo entero allí con su fecha y el commit que lo resolvió.

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
