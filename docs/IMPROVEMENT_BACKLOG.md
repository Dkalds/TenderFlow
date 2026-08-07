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

### [P2] Retirar el shim de paramstyle `?`→`%s` (codemod de 1123 ocurrencias)
- **Área:** db/connection.py, y todo el SQL del proyecto
- **Problema:** `_translate_qmarks` (`db/connection.py`) reescribe cada sentencia en runtime porque el SQL del proyecto se escribe en dialecto qmark y psycopg3 usa `%s`. Con SQLite retirado (ADR-021) **ya no es un hack de compatibilidad entre motores sino una convención de estilo**: se puede eliminar escribiendo el SQL directamente en `%s`. Sigue siendo deuda real — traduce en cada `execute` y ya causó un bug de producción (el escape de `%` literal, ver ADR-018) — pero acotada y cubierta por tests.
- **Por qué no se hizo dentro de ADR-021:** son **1123 ocurrencias de `?` en 57 archivos**, y `?` aparece también dentro de regex, docstrings y texto en español (`¿…?`), así que no admite un reemplazo textual. Bundlearlo con la retirada del motor habría producido un diff irrevisable y un `git bisect` inútil.
- **Acceptance criteria:**
  - `_translate_qmarks` y `_PgConnAdapter` eliminados; las conexiones son cursores psycopg3 desnudos.
  - Sin ocurrencias de placeholders `?` en SQL fuera de `db/alembic/versions/*`.
  - Suite verde entre cada archivo migrado (hacerlo por olas, no de una vez).
- **Files de partida:** [db/connection.py](../db/connection.py), [db/search_backend.py](../db/search_backend.py)
- **Riesgo:** medio — mecánico pero masivo; mitigado haciéndolo archivo a archivo con la suite como red.

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

### [P2] Sustituir los fixtures sintéticos del corpus CODICE por expedientes reales
- **Área:** tests/fixtures/placsp/
- **Problema:** los once casos del corpus golden son estructuralmente fieles al CODICE pero escritos a mano: la sesión que los creó no tenía ZIP mensuales cacheados ni acceso al feed. El valor del corpus está en codificar variabilidad que nadie imaginó, y eso solo lo dan los datos reales.
- **Acceptance criteria:**
  - `ENV=dev python scripts/capture_placsp_fixtures.py --caso <caso>` sustituye cada fixture sintético por uno real, y `python -m tests.test_codice_parser_golden --update` regenera el golden con el diff revisado.
- **Files de partida:** [scripts/capture_placsp_fixtures.py](../scripts/capture_placsp_fixtures.py), [tests/fixtures/placsp/README.md](../tests/fixtures/placsp/README.md)
- **Riesgo:** bajo — solo tests.

### [P2] UI de webhooks y GDPR self-service
- **Área:** web/, api/
- **Problema:** Backend completo sin superficie de usuario: `db/webhooks.py` tiene entrega HMAC funcional con retry/DNS-pinning, y existen export GDPR (`/me/data`) y delete de cuenta. Nada de eso es usable sin tocar la API a mano. Para consultoría, webhooks = integrar alertas con los sistemas del cliente — mucho valor por pocas pantallas.
- **Acceptance criteria:**
  - Página de gestión de webhooks: CRUD, ping de prueba, visualización de secret una sola vez, estado de entregas.
  - Página de cuenta con export de datos (descarga `/me/data`) y delete de cuenta con confirmación.
  - Consume exclusivamente la API tipada (invariante §3.8); tests vitest de los flujos.
- **Files de partida:** [db/webhooks.py](../db/webhooks.py), [api/routes/webhooks.py](../api/routes/webhooks.py), [api/routes/me.py](../api/routes/me.py), [web/src/app/(dashboard)/](../web/src/app/(dashboard)/)
- **Riesgo:** bajo — el backend ya existe; solo se añade frontend.

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

### [P3] Migrar los `title=` nativos restantes a `Tooltip`
- **Área:** web/src (celdas de tabla y textos truncados)
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

### [P3] Completar la migración de `title=` nativos a `ui/tooltip.tsx`
- **Área:** web/ (amplio)
- **Problema:** La revisión de las skills de Emil Kowalski (2026-07-25, ver `docs/frontend-motion.md`) migró a `components/ui/tooltip.tsx` (Radix, `skipDelayDuration`) los `title=` de los controles interactivos icon-only más visibles (preset menus de `GlobalFilterBar`, badge de anomalía de `KpiCard`, toggles de densidad/tema de `TopNav`). Quedan `title=` nativos en celdas de tabla truncadas y textos informativos (p. ej. `tecnologias/page.tsx`, `company-profile-summary.tsx`, `company-year-trend.tsx`) — el `title` nativo del navegador tiene delay fijo (~500ms), no se estiliza y no existe en táctil.
- **Acceptance criteria:**
  - Los `title=` sobre contenido truncado/informativo (no solo controles) migrados a `Tooltip`, envueltos en `TooltipProvider` donde haga falta.
  - Ningún `title=` nuevo se añade sin pasar antes por `Tooltip`.
- **Files de partida:** `grep -rn 'title=' web/src --include='*.tsx'` (excluyendo el prop `title` de `KpiCard`, que es el encabezado de la tarjeta, no un tooltip nativo)
- **Riesgo:** bajo — cosmético/accesibilidad, sin tocar datos; requiere `TooltipProvider` en los tests que rendericen los componentes migrados de forma aislada (ver `global-filter-bar.test.tsx` como ejemplo).

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
