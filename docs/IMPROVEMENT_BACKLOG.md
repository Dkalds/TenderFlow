# Improvement Backlog

Lista viva de mejoras conocidas, priorizadas. **Diseñada para que un agente pueda elegir un ítem y trabajarlo sin pedir contexto extra al usuario.**

## Convenciones

- **Prioridad**: P0 (urgente / bloquea) · P1 (alta) · P2 (media) · P3 (nice-to-have).
- **Riesgo**: bajo (cambio aislado) · medio (afecta varios módulos) · alto (toca core / migra schema / cambia contrato).
- Si añadís un ítem nuevo, copiá la plantilla del final.
- Al cerrarlo, no lo dejes tachado aquí: **movélo entero a la sección _Cerrados_** del final con la fecha y el commit/PR que lo resolvió. Las secciones P1/P2/P3 contienen **solo ítems abiertos**.

## Repaso del 2026-08-27 (auditoría de producto/UX)

Este fichero y [UX_AUDIT.md](UX_AUDIT.md) iban por detrás del código que citaban. Lo que cambió:

- **Cerrado y archivado:** el P1 de los enlaces caducados de PLACSP — entregado entero en `c230e63` (PR #191), no en los tres SHAs que el ítem citaba, que nunca llegaron a `master`. Ficha completa en [el archivo](archive/IMPROVEMENT_BACKLOG_CERRADOS.md).
- **Altas:** dos P1 (allowlist de acceso, `plan: free` frente al SLO) y dos P2 (onboarding de primer uso, experiencia móvil). El de la allowlist nace como **RFC**, no como PR: toca auth y necesita migración.
- **Cifras corregidas** en el P1 de cobertura del frontend: las páginas de 1.000+ líneas que citaba ya no existen.
- **Sigue abierto y no se tocó en esta tanda:** el P0 de los backups sin copia remota (configuración de infraestructura, acción del usuario) y la pata pendiente del P1 de scoring en frío (necesita índice o materialización, o sea migración con gate humano §6).

---

## P0 — Urgente

### [P0] Restablecer la copia remota de backups — rotos desde el 2026-07-05
- **Área:** .github/workflows/backup.yml, .github/workflows/restore-drill.yml, GitHub Settings (acción del usuario)
- **Problema:** `backup.yml` corre a diario y **falla siempre**, en ~45 s, sin llegar a volcar nada: muere en los guards `: "${AWS_ROLE_TO_ASSUME:?...}"` / `: "${BACKUP_S3_BUCKET:?...}"` (backup.yml:50-51) porque esos dos secrets no existen en el repo. Verificado el 2026-08-18: runs del 16, 17 y 18 de agosto en `failure`, y ninguno de los dos nombres aparece en `gh secret list`. Consecuencia: **no hay copia remota recuperable de ninguna fecha desde el 2026-07-05**, y `restore-drill.yml` (que verificaría que un backup restaura) está bloqueado por lo mismo, así que tampoco hay señal de que el mecanismo funcione. `BACKUP_ENCRYPTION_KEY` sí está cargada (2026-08-04), o sea que falta exactamente el destino, no el cifrado.
- **Acceptance criteria:**
  - `AWS_ROLE_TO_ASSUME` y `BACKUP_S3_BUCKET` cargados como GH Secrets (el rol necesita `s3:PutObject` sobre el bucket y confianza con el OIDC de Actions).
  - Un run de `backup.yml` en verde con el objeto verificado en S3.
  - Un run de `restore-drill.yml` en verde sobre ese backup — hasta que el drill pase, "hay backups" es una hipótesis.
- **Files de partida:** [.github/workflows/backup.yml](../.github/workflows/backup.yml), [.github/workflows/restore-drill.yml](../.github/workflows/restore-drill.yml), [docs/runbooks/backup-restore.md](runbooks/backup-restore.md)
- **Relación:** es la pata de infraestructura del checklist F3d (P1, más abajo), que cubre el cifrado y la rotación de credenciales pero da por hecho que el destino existe.
- **Riesgo:** bajo — solo configuración, sin tocar código. El riesgo real es el que ya se está corriendo cada día que pasa sin copia.

---

## P1 — Alta

### [P1] Ampliar el golden set del clasificador SAP a 300-500 ejemplos etiquetados a mano
- **Área:** tests/fixtures/golden_set.jsonl, tests/fixtures/golden_set_tech.jsonl, scripts/sample_golden_candidates.py (acción del usuario: etiquetar)
- **Problema:** el golden set es el único sitio del repo con etiquetas humanas independientes del filtro de keywords, y de él salen dos cosas que gobiernan producción: el umbral servido y `recall_no_keyword`, la métrica que decide si el ML aporta algo sobre `matches_sap()` (desde el 2026-08-24 es criterio **bloqueante** del gate de promoción, `services/ml/promotion.py`). Con 27 ejemplos no sostiene ninguna de las dos: solo 6 son positivos humanos sin keyword, así que `recall_no_keyword` se mueve a saltos de 16,7 puntos y solo puede tomar 7 valores; un bootstrap sobre esos 27 da un umbral con sigma=0,084 y rango p5-p95 de [0,30, 0,56] sobre un rango útil de 0,65, y el F-beta reportado sobre el mismo conjunto donde se elegía el umbral sobreestimaba el real en +0,08 de media (+0,25 en el p90). El reparto tune/holdout ya está implementado; partir 27 en dos no arregla el tamaño. El golden multi-etiqueta (`golden_set_tech.jsonl`) tiene 23 ejemplos semilla y el mismo problema.
- **Por qué no se cerró en el mismo cambio:** etiquetar requiere criterio humano sobre licitaciones reales. Fabricar cientos de ejemplos sintéticos mediría el texto que escribió quien los fabricó, no la realidad — un golden set inventado es peor que uno pequeño, porque el pequeño al menos se sabe pequeño.
- **Acceptance criteria:**
  - >= 60 ejemplos por mitad (`services.ml_eval.MIN_TUNE_EXAMPLES` / `MIN_HOLDOUT_EXAMPLES`); objetivo 300-500 en total.
  - >= 30 positivos humanos **sin keyword** en el holdout, para que `recall_no_keyword` tenga resolución útil.
  - `load_golden_set()` deja de emitir `golden_tune_split_too_small` / `golden_holdout_too_small`.
- **Cómo empezar:** `python -m scripts.sample_golden_candidates --n 400 --out /tmp/candidatos.jsonl` — muestrea estratificando por la zona de desacuerdo entre keywords y modelo, que es donde una etiqueta humana aporta información. Escribe `label: null` para rellenar a mano.
- **Files de partida:** [scripts/sample_golden_candidates.py](../scripts/sample_golden_candidates.py), [tests/fixtures/golden_set.jsonl](../tests/fixtures/golden_set.jsonl), [services/ml_eval.py](../services/ml_eval.py)
- **Riesgo:** bajo en código, alto en oportunidad — mientras el set sea pequeño, el gate de promoción bloquea con poca evidencia y el umbral servido tiene una varianza que ninguna mejora del modelo puede compensar.

### [P1] `make web-test` sale con exit 0 aunque no ejecute ni un test
- **Área:** web/vitest.config.ts, Makefile (`web-test`, `web-test-coverage`), CI
- **Problema:** cuando vitest no consigue arrancar sus workers, **no falla: reporta `Test Files no tests` / `Tests no tests` junto a N errores y termina con exit code 0**. Un gate que solo mira el código de salida da por verde una suite que no corrió. Reproducido tres veces seguidas el 2026-08-18/19 sobre el mismo árbol, con los dos pools: `--pool=forks --no-file-parallelism` → 70 de 113 ficheros ejecutados, 43 errores de arranque, **exit 0**; `--pool=forks` → **0 de 113**, 113 errores, **exit 0**; y un único fichero (`src/lib/__tests__/safe-redirect.test.ts`) con `--pool=threads` → `no tests`, 1 error, **exit 0**. El mensaje es siempre `[vitest-pool]: Failed to start forks worker` / `[vitest-pool-runner]: Timeout waiting for worker to respond` (START_TIMEOUT de 60 s, no configurable por CLI). En esta máquina lo dispara la contención (OneDrive + antivirus), pero la causa de fondo —**el runner no distingue "todo pasó" de "no se ejecutó nada"**— es del repo y viaja a CI: un runner lento o un contenedor apretado producen ahí el mismo falso verde, y el job saldría en verde sin haber probado nada.
- **Acceptance criteria:**
  - `make web-test` falla si el número de ficheros ejecutados es 0, o si hay errores de arranque de pool, aunque vitest devuelva 0. Basta con envolver la invocación y comprobar el resumen (o usar `--reporter=json` y asertar `numTotalTestSuites > 0`).
  - Un umbral mínimo de ficheros esperados, para que perder la mitad de la suite tampoco pase por verde. Es el mismo patrón de ratchet que ya usan `KNOWN_5XX` y la whitelist TID251.
  - Documentado en [docs/AGENT_PLAYBOOK.md](AGENT_PLAYBOOK.md) junto al resto de prerrequisitos.
- **Files de partida:** [Makefile](../Makefile) (línea ~183), [web/vitest.config.ts](../web/vitest.config.ts)
- **Riesgo:** bajo — envuelve un comando, no toca tests. El riesgo es el de no hacerlo: es un gate que miente en la dirección peligrosa.

### [P1] Aprobar un acceso es editar variables de entorno a mano — decisión de auth, necesita RFC
- **Área:** config/settings.py, api/routes/admin_solicitudes.py, render.yaml, db/ (acción del usuario + RFC)
- **Problema:** el embudo público ya está entero salvo el último paso. `POST /publico/solicitudes-acceso` registra la petición, `GET/PATCH /admin/solicitudes-acceso` da la cola, y el aviso por correo al solicitante existe (`services/solicitudes_acceso.py::notificar_acceso_concedido`, opt-in por operación) — o sea que **la promesa de `solicitud-recibida/page.tsx` ("la respuesta llega por correo") ya se puede cumplir**, cosa que hasta la PR #215 no era cierta. Lo que sigue abierto es que **conceder el acceso no está en el producto**: la allowlist son dos strings de entorno (`OAUTH_ALLOWED_EMAILS`/`OAUTH_ALLOWED_DOMAINS`, `config/settings.py:258-259`, declaradas con `sync: false` en `render.yaml:110-113`), así que aprobar a alguien es entrar al panel de Render, editar una variable y esperar el redeploy. De ahí salen dos consecuencias: el `notificar` del PATCH es opt-in **precisamente porque el sistema no puede saber si la allowlist ya se editó** (un correo antes de tiempo manda a la persona contra un 403), y no queda rastro de quién concedió qué acceso ni cuándo.
- **Ojo al leer esto:** la descripción de arriba se escribió contra el **working tree** del 2026-08-27, donde `api/routes/admin_solicitudes.py` y `services/solicitudes_acceso.py` estaban recién tocados y `docs/runbooks/conceder-acceso.md` sin commitear. Si ese trabajo ha aterrizado, la pata del aviso por correo ya está cerrada y lo único que queda abierto de este ítem es la allowlist; confirmá el estado del runbook antes de empezar.
- **Por qué esto NO es un PR directo:** mover la allowlist a base de datos es (a) una **migración** —tabla nueva, gate humano de AGENTS.md §6— y (b) un cambio en el **camino de autenticación**, que según AGENTS.md §5 exige RFC antes de escribir código. Un agente que "solo" añadiera la tabla ya habría decidido por su cuenta dónde vive la verdad del acceso.
- **Acceptance criteria:**
  - RFC en `docs/rfc/` que decida: allowlist en BD frente a seguir en entorno; qué pasa con el fail-closed que hoy garantiza el validador de `config/settings.py` cuando ambas variables están vacías en prod; y si el PATCH pasa a conceder el acceso de verdad (y entonces `notificar` deja de ser opt-in) o se queda como cola de trabajo.
  - Solo después: migración con OK humano, endpoint, y registro del alta en `db/audit.py` como el resto de acciones de admin.
- **Files de partida:** [api/routes/admin_solicitudes.py](../api/routes/admin_solicitudes.py), [config/settings.py](../config/settings.py), [services/solicitudes_acceso.py](../services/solicitudes_acceso.py), [render.yaml](../render.yaml)
- **Riesgo:** alto — es el control de acceso al producto. Un error aquí abre la aplicación o deja fuera a quien ya entraba; por eso el RFC va antes que el código.

### [P1] La API de producción corre en `plan: free` y el SLO de disponibilidad dice 99 %
- **Área:** render.yaml, docs/sli-slo.md, infraestructura (decisión del usuario, con coste)
- **Problema:** `render.yaml:25` declara `plan: free` para `tenderflow-api`. El plan gratuito de Render hace **spin-down por inactividad**, así que la primera petición tras un rato de silencio paga el arranque en frío entero, y el contenedor tiene 512 MB — el mismo donde ya hubo un OOM (comentario de `api/app.py`). Enfrente, [docs/sli-slo.md](sli-slo.md) fija **≥ 99 % de disponibilidad a 30 días** (7,2 h/mes de presupuesto de error) y **P99 < 500 ms**. Un servicio que se apaga solo no puede firmar ninguno de los dos, y el `healthCheckPath` de `render.yaml:34` no lo arregla: mide si responde, no si estaba despierto. O se sube el plan o se corrige el SLO — mantener ambos escritos es tener un objetivo que nadie mide contra una infraestructura que no puede cumplirlo.
- **Acceptance criteria (decisión del usuario):**
  - Decidido y escrito: se sube el plan de `tenderflow-api`, o `docs/sli-slo.md` baja el objetivo al que el plan free sí sostiene, diciendo por qué.
  - Si se sube el plan: `render.yaml` actualizado, y el spin-down descartado como causa en la primera lectura de disponibilidad posterior.
- **Files de partida:** [render.yaml](../render.yaml), [docs/sli-slo.md](sli-slo.md)
- **Relación:** comparte superficie con el P2 de `render.yaml` sin vincular al Blueprint y con el P3 de staging; si se toca el servicio, conviene decidir los tres a la vez.
- **Riesgo:** bajo técnico, con coste económico — por eso es decisión del usuario.

### [P1] El contexto de scoring cuesta ~25 s en frío en cada instancia nueva
- **Área:** db/repositories/aggregates.py, services/analytics/scoring_signals.py
- **Problema:** acotar el universo puntuable (commit del fix del Radar, 2026-08-11) quitó el escaneo de 1,5 M filas, pero `_build_context` sigue pagando tres consultas de contexto que no dependen de la fila puntuada y que escanean la tabla entera. Medido en producción el 2026-08-11: `importe_percentiles()` **7,4 s** (seq scan + sort de 1,63 M importes, y a diferencia de las señales **no está cacheada**: se llama en cada request), la media de ofertas por CPV-4 de `load_competencia_stats` **9,5 s** (hash join de 1,6 M adjudicaciones contra un Parallel Seq Scan de `licitaciones` filtrando por `analysis_universe`, que no tiene índice utilizable), más las tres consultas de `load_margen_stats`. Total observado de un request en frío: **59,6 s** (correlation_id `93da5a9b`, 25 filas puntuadas) frente a 186 ms con caché caliente. Ya no tumba el proceso —las cachés ahora sobreviven porque la instancia deja de reiniciarse—, pero la primera carga del Radar tras cada deploy o expiración de TTL paga eso entero.
- **Acceptance criteria:**
  - Primera carga del Radar en una instancia fría por debajo de 5 s.
  - ~~`importe_percentiles()` cacheada con el mismo patrón `SignalAwareCache` que ya usan las señales (P10/P90 globales cambian con la ingesta, no con el request), o materializada.~~ **Hecho 2026-08-12**: `load_importe_percentiles()` cachea con `SignalAwareCache` y además consulta `importe_percentiles_universo()`, que agrega sobre las ~1,6 k filas del universo puntuable usando `idx_lic_fecha_limite` en vez de escanear 1,63 M importes. El método global queda solo como fallback cuando la muestra viva no llega a 50 importes.
  - La media de ofertas por CPV-4 deja de escanear `licitaciones` entera: índice que sirva el predicado de `analysis_universe`/`cpv`, o agregado materializado por CPV-4. **Pendiente** — es lo que mantiene este ítem abierto: necesita migración (índice o materialización), y tocar `db/alembic/` requiere OK humano explícito (AGENTS §6). Sin esta pata, el frío absoluto sigue por encima de 5 s aunque los percentiles ya no aporten sus 7,4 s.
- **Files de partida:** [db/repositories/aggregates.py](../db/repositories/aggregates.py) (`importe_percentiles_universo`), [services/analytics/scoring_signals.py](../services/analytics/scoring_signals.py), [services/_data_cache.py](../services/_data_cache.py)
- **Riesgo:** bajo — cachear un agregado global y añadir un índice; sin cambio de contrato. Sí cambian los números mostrados: los percentiles pasan a describir el mercado abierto y no la tabla entera (deliberado, ver addendum del RFC de scoring).

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
- **⚠️ Estado real, verificado el 2026-08-18: casi todo esto ya está implementado y el backlog no se había actualizado.** Existe `llm/budget.py` con `BudgetGuard` (acumulador por ventana día/mes en Redis con `INCRBYFLOAT`+TTL y fallback in-memory), tope **por sujeto** además del global (sin él una sola cuenta agota la ventana de todas — denegación de servicio barata), `LLM_BUDGET_USD_DAILY`/`_MONTHLY`/`_DAILY_PER_USER` en settings, y `/ask` con `_check_budget`, 429 documentado y el evento SSE `degraded` para el fallback sin síntesis. Un detalle que el backlog decía al revés: `LLM_BUDGET_MODE` **ya está en `enforce`**, no en `monitor` como declaraba la nota de riesgo.
- **Acceptance criteria:**
  - ~~Con presupuesto superado y `LLM_BUDGET_MODE=enforce`, `/ask` responde 429/503 sin llamar al proveedor; `llm_budget_exceeded_total` sube. Modo `monitor` solo alerta.~~ **Hecho** (`llm/budget.py`, `api/routes/ask.py`).
  - ~~Ante fallo del proveedor o breaker abierto, `/ask` degrada a documentos del RAG sin síntesis (`degraded` en el stream); el SSE no rompe y el DTO no cambia (§3.5).~~ **Hecho** (`api/routes/ask.py`, eventos `degraded` por `provider_error`, `timeout` y `empty_response`).
  - Eval de **recuperación** determinista en CI (sin LLM real) que falla si se rompe el contexto recuperado. **Es lo único que mantiene abierto este ítem.**
- **Files de partida:** [api/routes/ask.py](../api/routes/ask.py), [llm/client.py](../llm/client.py), [config/settings.py](../config/settings.py), [docs/adr/[[ADR-006-etag-pdf-export-ratelimit-redis|ADR-006]]-etag-pdf-export-ratelimit-redis.md](../docs/adr/ADR-006-etag-pdf-export-ratelimit-redis.md)
- **RFC:** [2026-06-30-rfc-llm-dependencia-gestionada.md](rfc/2026-06-30-rfc-llm-dependencia-gestionada.md)
- **Riesgo:** medio — toca un endpoint de producción; mitigado por `LLM_BUDGET_MODE=monitor` como default (medir antes de cortar) y contrato API intacto. **Construye sobre** el RFC de observabilidad de tokens (P2, abajo).

---

## P2 — Media

### [P2] `HistGradientBoosting` revienta si una feature llega entera a NaN
- **Área:** services/ml/baja_model.py, services/ml/features.py, tests/test_ml_baja_model.py
- **Problema:** con las versiones pineadas (numpy 2.4.4, scikit-learn 1.9.0), ajustar `HistGradientBoostingRegressor` sobre una matriz con **una columna enteramente NaN** falla con `ValueError: window shape cannot be larger than input array shape` en `sklearn/ensemble/_hist_gradient_boosting/binning.py:82`. La causa es precisa: `_find_binning_thresholds` guarda el caso de una columna **constante** (`if len(distinct_values) == 1: return []`) pero no el de **cero** valores distintos, que es lo que deja una columna todo-NaN tras descartar los missing; entonces `sliding_window_view(distinct_values, 2)` recibe un array vacío. Reproducido aislado: columna todo-NaN → ValueError; columna constante → OK.
- **Estado de la evidencia (importante):** **no reproduce en CI.** `master` está verde en el mismo commit base (run #830 sobre `5164793`), y CI corre la suite entera sin filtro de marcadores. Sí reproduce en el contenedor de sesiones remotas —sobre un worktree limpio de `5164793` y sobre la rama de trabajo, con Python 3.11 y 3.13 y las versiones pineadas— en `test_entrenar_registra_version_y_metricas`, `test_predicciones_del_modelo_distinguen_segmentos` y `test_scoring_degrada_a_baseline_si_el_layout_no_coincide`. Qué hace que la matriz salga con una columna todo-NaN aquí y no allí **está sin identificar**: el histórico sintético de `_sembrar_historico` es determinista (fechas fijas, CPV/CCAA/tipo/fuente constantes), así que la diferencia tiene que estar en el entorno o en el estado de la BD, no en el fixture.
- **Por qué merece entrada igualmente:** el docstring de `FEATURES_PENDIENTES_COBERTURA` ya avisa de que "una feature NULL en el 90% de las filas no es neutra". Aquí la consecuencia es peor que un split desperdiciado: al 100% de NULL el ajuste **no arranca**. Cualquier feature nueva con cobertura baja puede tumbar el reentrenamiento en vez de degradarlo.
- **Acceptance criteria:**
  - Identificado qué diferencia de entorno produce la columna todo-NaN aquí y no en CI (o descartado como artefacto del contenedor, dejándolo escrito).
  - `baja_model` descarta las columnas sin ningún valor observado antes del ajuste, con log de cuáles y un test que fije el invariante — el reentrenamiento no puede depender de que ninguna feature llegue vacía.
- **Files de partida:** [services/ml/baja_model.py](../services/ml/baja_model.py), [services/ml/features.py](../services/ml/features.py)
- **Riesgo:** bajo — el serving ya degrada al baseline si el modelo no existe, que es el comportamiento previsto para un fallo de entrenamiento.


### [P2] `render.yaml` no gobierna el servicio que corre en producción
- **Área:** render.yaml, Render Dashboard (acción del usuario)
- **Problema:** el Blueprint está en el repo, pero el servicio de producción se creó a mano por el dashboard y nunca se vinculó a él, así que el fichero documenta una intención que nadie aplica: editarlo no cambia nada y leerlo puede inducir a error sobre cómo está configurado el servicio real. Lo que sí está activo es `autoDeploy`, y **sin healthcheck configurado** — es decir, un deploy que arranca mal reemplaza igualmente al que funcionaba, sin rollback automático. (Estado observado en la sesión del 2026-08-04; **reconfirmar en el dashboard antes de actuar**, que es barato.)
- **Acceptance criteria:**
  - Confirmado en el dashboard si el servicio está o no vinculado al Blueprint.
  - `healthCheckPath` configurado y verificado con un deploy deliberadamente fallido (o, si se vincula el Blueprint, que el del fichero quede efectivo).
  - Si se decide no vincular, dejarlo escrito en `render.yaml` para que el fichero no siga aparentando ser la fuente de verdad.
- **Files de partida:** [render.yaml](../render.yaml), [.github/workflows/deploy.yml](../.github/workflows/deploy.yml)
- **Relación:** comparte superficie con el P3 de staging y plan de la API (más abajo); si se toca el servicio, conviene decidir ambos a la vez.
- **Riesgo:** bajo-medio — vincular un Blueprint a un servicio existente puede recrearlo; hacerlo en ventana y con el healthcheck decidido de antemano.

### [P2] Migrar `licitaciones.importe` de `real` a `double precision`
- **Área:** db/alembic, db/upsert.py, shared/numeric.py
- **Problema:** la columna es `real` (float4, 4 bytes ≈ 7 cifras significativas) en producción mientras que los conectores escriben `float` de Python (float8): el valor que vuelve del SELECT nunca coincide con el que se escribió. El detector de diffs de `db/upsert.py::_upsert_chunk` comparaba con `!=` exacto y marcaba "importe cambió" en **cada** re-ingesta de un expediente intacto. Medido el 2026-08-16: un backfill de TED generó 635 filas de `licitaciones_history` con `changed_fields='importe'` y en los 7 días previos hubo 1.150 más —una tanda por run del cron—; ningún importe había cambiado (desvío relativo máximo snapshot↔actual: 4,96e-6, el límite de precisión de float4). También afectaba a `placsp` y `pscp`. **Mitigado el 2026-08-16** comparando con tolerancia relativa (`shared/numeric.py::values_equal`, `FLOAT_REL_TOL = 1e-5`) en el detector de diffs y en `services/contract_events.py::_classify` — este último protege además de las filas basura ya escritas, que siguen en la tabla y el cursor de eventos acabará procesando. Queda abierto el arreglo de raíz: mientras la columna sea float4, la tolerancia es obligatoria y ciega a cambios reales por debajo del 0,001 % (10 € en 1 M€).
- **Acceptance criteria:**
  - `licitaciones.importe` en `double precision` en producción, y `duracion_valor` con el mismo criterio (mismo tipo, mismo ruido).
  - `FLOAT_REL_TOL` baja al ruido residual de float8 (o la tolerancia se retira del campo) **sólo después** de verificar el tipo en producción, no en el mismo commit que la migración.
  - Limpieza de las filas de `licitaciones_history` con `changed_fields='importe'` cuyo snapshot no difiere del valor actual más allá de la tolerancia, y de los `contrato_eventos` de tipo `modificacion` derivados de ellas.
- **Ojo con la ventana:** requiere **OK humano explícito** (AGENTS.md §6, `db/alembic/`) y no se lanza a ciegas. `ALTER TABLE licitaciones ALTER COLUMN importe TYPE double precision` **reescribe la tabla entera** (~1,3 M filas) con lock `ACCESS EXCLUSIVE`, además de reconstruir `idx_lic_importe`. Hay precedente directo: la columna generada de `v68_fecha_pub_date_generated` tardó >30 min con lock exclusivo y no cupo en la ventana de mantenimiento. El plan que sí cabe es el de columna sombra: añadir `importe_f8`, backfillear por lotes, cambiar lecturas/escrituras y renombrar en una ventana corta.
- **Nota de deriva de schema:** `alembic upgrade head` crea la columna como `double precision` (`sa.Float` en `baseline002_pg_core_genesis`), así que **CI y cualquier bootstrap nuevo no reproducen el bug**: el `real` de producción viene del schema SQLite pre-ADR-021. Los tests de regresión (`tests/test_db_upsert.py::test_reingesta_identica_no_genera_historial_con_importe_float4`) alinean la columna con producción vía `ALTER` en una fixture para poder medir algo.
- **Files de partida:** [db/upsert.py](../db/upsert.py), [shared/numeric.py](../shared/numeric.py), [services/contract_events.py](../services/contract_events.py), [db/alembic/versions/baseline002_pg_core_genesis.py](../db/alembic/versions/baseline002_pg_core_genesis.py)
- **Riesgo:** alto — migra schema de la tabla núcleo con lock exclusivo sobre 1,3 M filas; la mitigación aplicada (tolerancia) es de riesgo bajo y ya cubre el síntoma.

### [P2] Separar los requirements de la API de los del pipeline/ML
- **Área:** requirements.in, docker/
- **Problema:** las 33 deps runtime (pandas, scikit-learn, statsmodels, networkx, reportlab, boto3, lxml, openai…) viven en un único deployable: la imagen de la API que corre en 0.1 vCPU/2GiB paga memoria, cold start y superficie de ataque de librerías que solo usa el plano de ingesta/ML. El OOM del 2026-08-02 (comentario en `api/app.py`) es el síntoma de fondo: OLAP y ML dentro del proceso HTTP. Con 38 avisos de Dependabot abiertos (29 high), reducir lo que instala la imagen expuesta a internet también encoge la superficie que hay que parchear.
- **Acceptance criteria:**
  - `requirements-api.in` y `requirements-pipeline.in` compilados por separado (mismo flujo pip-tools con hashes).
  - La imagen de la API no instala scikit-learn/statsmodels/networkx salvo que una ruta los importe de verdad (los imports lazy existentes delimitan el corte).
  - CI construye ambas variantes y el smoke de la API pasa con la imagen reducida.
- **Files de partida:** [requirements.in](../requirements.in), [docker/](../docker/)
- **Riesgo:** medio — toca dependencias (gate humano §6) y puede destapar imports implícitos; mitigado con smoke de import por entrypoint.

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
- **Problema:** Con el denominador corregido el 2026-08-10 (antes se excluía `src/app/**` entero alegando que son Server Components, y la mayoría de las páginas son `"use client"`), la cobertura real del frontend es **40.2/30.4/37.5/41.6**, no el 68/63/68/70 que CI parecía exigir. Las páginas están al 0%: ahí vive la lógica de filtros, mutaciones y derivación. Los pisos por carpeta de `lib`/`hooks`/`components` conservan la garantía anterior, pero el conjunto está descubierto.
- **Cifras actualizadas 2026-08-27:** las tres páginas que este ítem citaba con 1.000+ líneas (`competidores` 1.047, `mi-watchlist` 1.044, `detalle` 1.015) **ya no las tienen**: hoy son `detalle` 929, `mi-watchlist` 917 y `competidores` 867, porque su lógica salió a `_hooks/` (las tres tienen ya ese directorio, y `vitest.config.ts` mide `src/app/**/_hooks/*.ts` al 99,67 % de sentencias). O sea que el segundo criterio de aceptación está a medias por las tres de arriba y sin empezar por el resto. Los porcentajes globales **no se han vuelto a medir en esta sesión** (`make web-test` no se ejecutó): los 40.2/30.4/37.5/41.6 son del 2026-08-10 y hay que releerlos antes de usarlos como baseline.
- **Acceptance criteria:**
  - Tests de los 3 flujos críticos que siguen sin cubrir: filtros nuqs (`web/src/lib/filters.ts` ya cubierto; falta su uso desde las páginas), watchlist (`use-watchlist-items`), streaming SSE de `/ask` (`ask-stream.ts`).
  - Seguir extrayendo a hooks testeables la lógica de las páginas más grandes, en vez de testear el árbol entero. Siguientes por tamaño tras las tres ya extraídas: `tecnologias` 734, `organos` 649, `radar` 635.
  - Subir los umbrales globales de `vitest.config.ts` conforme suba lo medido. **No bajar los pisos por carpeta.**
- **Files de partida:** [web/vitest.config.ts](../web/vitest.config.ts), [web/src/lib/ask-stream.ts](../web/src/lib/ask-stream.ts)
- **Riesgo:** bajo — solo añade tests.

### [P2] La consola no tiene primer uso: se entra a 14 espacios sin que nadie explique ninguno
- **Área:** web/src/components/layout, web/src/app/(dashboard)
- **Problema:** no existe onboarding de ningún tipo — cero coincidencias de `onboarding` en todo `web/src`. Quien entra por primera vez aterriza en `/resumen` con el rail de 14 espacios (`web/src/lib/console-spaces.ts`) y una barra de ámbito ya aplicada, y deduce por su cuenta qué es el Radar, en qué se diferencia de Oportunidades y qué significa el score que abre cada tarjeta. En un producto que vende **confianza en el dato**, un número sin explicar la primera vez que se ve no se lee como preciso: se lee como opaco.
- **Acceptance criteria:**
  - Un recorrido de primer uso, descartable y que no vuelva —persistido por usuario en servidor, no en `localStorage` (invariante 2 de [frontend-data-invariants.md](frontend-data-invariants.md))— que explique al menos qué ordena el Radar, qué es el ámbito de la `scope-bar` y de dónde sale el score.
  - Estados vacíos que enseñen en vez de solo informar: el patrón de "sin resultados" ya existe; lo que falta es que diga qué hacer.
- **Files de partida:** [web/src/lib/console-spaces.ts](../web/src/lib/console-spaces.ts), [web/src/components/layout/console-rail.tsx](../web/src/components/layout/console-rail.tsx)
- **Riesgo:** bajo — aditivo, sin tocar datos; el cuidado está en no fabricar explicaciones que el backend no respalde.

### [P2] La experiencia móvil existe pero nadie la diseñó
- **Área:** web/src/components/layout, web/src/app/(dashboard)
- **Problema:** por debajo de `md` el rail de espacios es `hidden` (`console-rail.tsx:196`) y la única navegación es el drawer del `Sheet` (`console-rail.tsx:242-258`). Eso **ya está cubierto por un test real** (`web/e2e/responsive.spec.ts` a 375×812, sin `.or()` ni condicionales), así que no es un agujero de verificación: es que el contenido que hay detrás del drawer no está pensado para ese ancho — lo que llenan las páginas son tablas densas y grafos. El selector de organización del propio rail sigue además siendo un `<select>` nativo (`console-rail.tsx:125`) mientras el resto de controles son Radix: comportamiento de teclado y de lector distinto.
- **Acceptance criteria:**
  - Decidido y escrito qué significa "móvil" aquí: consulta puntual (leer una ficha, mirar una alerta) o consola completa. Sin esa decisión, cada página lo resuelve distinto.
  - Las tablas de las páginas del alcance elegido tienen presentación propia por debajo de `md`, no un scroll horizontal de la de escritorio.
  - El selector de organización pasa a Radix, alineado con `ui/multi-select.tsx`.
- **Files de partida:** [web/src/components/layout/console-rail.tsx](../web/src/components/layout/console-rail.tsx), [web/e2e/responsive.spec.ts](../web/e2e/responsive.spec.ts)
- **Riesgo:** bajo — presentación; sin tocar contratos ni datos.

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

### [P3] Descartar los avisos fantasma de Dependabot (manifest `uv.lock` inexistente)
- **Área:** GitHub Security (acción del usuario), .github/dependabot.yml
- **Problema:** buena parte de los avisos pip abiertos apuntan a un `uv.lock` que **no está trackeado en git** (verificado el 2026-08-18: `git ls-files` no lo encuentra). Son alertas sobre un manifest que no existe en el repo, así que no hay nada que parchear en ellas — pero ocupan el mismo listado que los avisos reales, y un tab de seguridad con decenas de entradas irreales se deja de mirar. Al triar, filtrar por `manifest_path`.
- **Acceptance criteria:** avisos cuyo `manifest_path` sea `uv.lock` descartados con motivo; el listado de seguridad refleja solo manifiestos que el repo contiene de verdad.
- **Files de partida:** [.github/dependabot.yml](../.github/dependabot.yml)
- **Riesgo:** bajo — no toca código; el cuidado está en descartar solo los del manifest fantasma.

### [P3] Suites propias para `services/investigador/` y `extraction_runs`
- **Área:** tests/
- **Problema:** ambos módulos se ejercitan hoy solo de refilón, desde tests de search y de pipeline que van a otra cosa. Eso da cobertura de líneas pero no fija su contrato: un cambio de comportamiento puede pasar si los tests que lo tocan siguen verdes por lo que ellos venían a comprobar.
- **Acceptance criteria:** un `tests/test_investigador*.py` y un `tests/test_extraction_runs.py` que cubran sus caminos principales y sus errores esperados, sin depender de la suite que hoy los roza.
- **Riesgo:** bajo — solo añade tests.

### [P3] Decidir el destino del peso de `graphify-out/` (28 MB y creciendo)
- **Área:** graphify-out, .claude/hooks
- **Problema:** los artefactos commiteados del knowledge graph pesan **28 MB** (medido 2026-08-18): cada clone y cada sesión remota los paga, y el hook de stale-flag deja el working tree dirty en sesiones sin el CLI (que no pueden limpiarlo). El valor para agentes sin CLI es real (AGENTS.md §1), así que es un trade-off consciente a revisar, no un error. **La cifra de este ítem estaba desactualizada: decía 17 MB, o sea que el artefacto creció un 65% mientras la decisión seguía aplazada.** La comparación "~52% del repo" ya no es evaluable tal cual y se retira; lo que decide es el absoluto y su tendencia.
- **Acceptance criteria:**
  - Decisión registrada: mantener como está, excluir `wiki/` (la parte más pesada y más regenerable), o mover a artefacto de CI/LFS con fallback textual documentado en AGENTS.md §1.
- **Files de partida:** [AGENTS.md](../AGENTS.md), [.claude/hooks/](../.claude/hooks/)
- **Riesgo:** bajo — decisión de mantenedor; sin impacto en runtime.

### [P3] Los dos módulos-dios: `aggregates.py` y `settings.py`
- **Nota:** este ítem estaba **duplicado**. Había una segunda entrada, "Partir los dos módulos-dios: `aggregates.py` y `settings.py`", sobre los mismos dos ficheros y con criterios que se contradecían: una decía "no big-bang, solo dejar de crecer" y la otra "partir por dominio". Fusionados el 2026-08-18 (mismo patrón que la fusión de los `title=` el 2026-08-10). El criterio que sobrevive es el gradual, que es el que el repo ha demostrado que sí ejecuta.
- **Área:** db/repositories/aggregates.py, config/settings.py
- **Problema:** `db/repositories/aggregates.py` son 1.327 líneas y 55 funciones en una sola clase que concentra toda la analítica; `config/settings.py` son 946 líneas con 26 validadores en una clase plana que mezcla ejes ortogonales (BD, ML, LLM, auth, scraper, observabilidad) que ya están conceptualmente separados por `APP_PROFILE`. Son los dos ficheros que todo el mundo tiene que tocar, y donde se concentran los conflictos de merge. (`shared/dto.py`, en contraste, está sano: 620 líneas / 45 clases.)
- **Acceptance criteria:**
  - Una agregación o setting **nuevo** va a un módulo hermano (`aggregates_<área>.py` / settings por dominio) en vez de sumar al monolito.
  - Al tocar un bloque cohesivo existente **por otro motivo**, se evalúa extraerlo en el mismo cambio. El destino de `AggregateRepository` es partido por dominio (overview / geografía / competidores) y el de `Settings` submodelos anidados por eje preservando los nombres de variables de entorno — pero **llegando por partes, con la suite verde entre cada una**, no en un big-bang.
- **Files de partida:** [db/repositories/aggregates.py](../db/repositories/aggregates.py), [config/settings.py](../config/settings.py)
- **Riesgo:** bajo si se hace oportunista; medio si alguien intenta el big-bang.

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
- **Progreso 2026-08-10 — primera ola, 38 → 36:** `services/job_locks.py` entero pasa a `db/job_locks.py` (aprovechando que había que corregir su `release()`, que borraba locks ajenos) y el `SELECT 1` de `services/health.py` pasa a `db.connection.ping()`. El ratchet llevaba meses sin moverse; la lección de esta ola es que sale barato cuando se hace **al pasar por el módulo por otro motivo**, no como pasada dedicada.
- **Progreso 2026-08-18 — 34 → 32:** `services/licitaciones.py` y `services/ml/retencion_labels.py` salen de la whitelist; su SQL pasa a `db/repositories/licitaciones.py` y `db/repositories/adjudicaciones.py`, con tests de caracterización escritos **antes** de mover. El listado de renovaciones también se movió a `db/repositories/renovaciones.py` (ítem de `/renovaciones`, ver Cerrados), pero su entrada del ratchet **no se puede quitar todavía** porque los agregados hermanos (`resumen_renovaciones`/`totales_renovaciones`) siguen en `services/`.
- **Corrección de conteo:** la cifra "38 → 36" de la ola anterior nunca cuadró con [STATUS.md](STATUS.md), que el 2026-08-13 ya contaba **34**. La cifra buena es siempre la de STATUS.md, que se genera con `make status`; anotar el conteo a mano en este fichero solo produce dos números que se contradicen.
- **Dos efectos colaterales que esta migración tiene y nadie había registrado** (descubiertos el 2026-08-18 al ejecutar la ola):
  1. **Erosiona el guardrail de dedupe.** `tests/test_dedup_guardrail.py` escaneaba solo `services/`; mover SQL analítico a `db/` lo sacaba de su radio en silencio. Ya está corregido (el escáner tiene ahora una lista explícita de módulos de `db/`), pero **cada ola futura debe añadir a `_SCANNED_FILES` el módulo de `db/` que crea**, en el mismo cambio. Lo que destapó al ampliarlo es un ítem P1 propio.
  2. **Tienta a invertir las capas.** Al mover una query se mueven con ella los fragmentos SQL que interpola, y el reflejo es importarlos de `services/` — que ADR-024 prohíbe (`db/` no depende de `services/`). El destino correcto es `db/sql_fragments.py`, creado el 2026-08-18 con `FECHA_FIN_SQL`, `TECHNOLOGY_OBSERVED_SQL` y `exclude_duplicados_sql`; `services/` los reexporta.
- Siguientes candidatos por coste (conteo de `connect(`+`execute(`): `services/ml/calibration.py` (1), `services/entity_resolution.py` (1), `services/competitive/bajas.py` (2), `services/ml/features.py` (2).
- **Candidato aparte, por rendimiento en seguridad y no por coste:** `services/competitive/mercado.py` concentra ~12 de los ~30 `# noqa: S608` del repo (conteo del 2026-08-18). Cada supresión está justificada una por una y el idioma de fragmentos constantes está documentado en `services/sql_fragments.py`, así que no es un bug — pero es la mayor densidad de SQL interpolado del proyecto en un solo fichero, y cada filtro nuevo que se añade ahí es otra oportunidad de que un valor entre por concatenación sin que nadie lo note. Al moverlo a `db/`, hacerlo con un builder de `WHERE` testeado en lugar de arrastrar la interpolación tal cual (patrón de `tests/test_adjudicaciones_dedupe_sql.py`, que verifica que los `%s` siguen cuadrando con los parámetros).
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
- **Progreso 2026-08-12:** resuelta la mitad barata — el KPI del resumen ya no se llama "Calientes" en la UI (`kpi-rows.tsx` → "Grandes en plazo", `notification-bell.tsx` → "Grandes"), así que dos números distintos dejan de compartir nombre. El campo `ResumenHoyResult.calientes` se conserva porque es contrato público, con la advertencia en su docstring.
- **Progreso 2026-08-13:** el otro extremo del vector de confusión desapareció con la retirada de `/pipeline-alertas` (rediseño de Mi Pipeline, ver `docs/redesign/mi-pipeline-inventario.md`): el KPI "Calientes" por banda de score ya no tiene superficie propia —la banda de score vive solo en el Radar— y las tarjetas del resumen enlazan ahora a `/detalle`. Queda el criterio de aceptación sobre qué definición adopta el resumen.
- **Acceptance criteria (lo que queda):**
  - Decidir si el resumen adopta la banda de scoring (señal más rica) o mantiene su heurística de importe con el nombre nuevo. Si adopta el score, renombrar también el campo del DTO en una migración consciente del contrato (AGENTS §3.5).
- **Files de partida:** [services/analytics/resumen.py](../services/analytics/resumen.py), [services/analytics/pipeline.py](../services/analytics/pipeline.py), [services/analytics/scoring.py](../services/analytics/scoring.py)
- **Riesgo:** bajo — cambia un número visible en dos KPIs; sin migración de schema.

### [P3] El embudo del Resumen mide sus porcentajes contra todo el corpus
- **Área:** db/repositories/aggregates (`overview_funnel`), services/analytics/overview
- **Problema:** `overview_funnel` divide cada escalón (`PUB`, `EV`, `RES`, `ADJ`, `ANUL`) entre `COUNT(*)` de la tabla filtrada, no entre las filas que participan en el embudo. Con los 645.664 expedientes en `AGR` —que no son un escalón de nada: son avisos agregados de contratos ya celebrados— los cinco escalones suman ~6,7% y el 93% restante es invisible. El embudo se lee como si el 93% de los expedientes se hubieran perdido entre publicación y adjudicación.
- **Origen:** salió al normalizar `licitaciones.estado` (migración v91, 2026-08-26). La normalización no lo causó ni lo arregla: sólo lo hace explicable, porque hasta entonces ese 93% ni siquiera tenía nombre.
- **Acceptance criteria:**
  - Decidir el denominador: o los cinco escalones (`pct` suma 100 y el embudo se lee como embudo), o el corpus entero pero rotulando en la UI qué queda fuera. Lo que no puede quedarse es un porcentaje sin denominador declarado.
  - Si cambia `FunnelStep.pct`, es un cambio de semántica sobre contrato público (AGENTS §3.5): documentarlo en el DTO.
- **Files de partida:** [db/repositories/aggregates.py](../db/repositories/aggregates.py), [services/analytics/overview.py](../services/analytics/overview.py)
- **Riesgo:** bajo — cambia un porcentaje mostrado; sin migración de schema.

### [P3] Vigilar el crecimiento de `predicciones_baja`
- **Área:** services/analytics/scoring_signals, services/ml/scoring, scheduler/jobs/ml_predicciones
- **Problema:** `_load_margen_stats_raw` carga la tabla entera (`licitacion_id`, `p50`) a un dict en cada refresco de caché. Hoy es barato —el job de ML solo predice licitaciones abiertas, 5 k por corrida— pero el upsert **no purga**, así que la tabla acumula filas de expedientes ya cerrados y crece de forma monótona. No se filtra por universo vivo a propósito: el modo page-aligned del Detalle puntúa filas cerradas y perdería su dimensión de margen en silencio.
- **Acceptance criteria:**
  - Vigilar el campo `predicciones` del log `scoring_signals_margen_cargada`.
  - Si supera ~200 k filas, purgar por antigüedad en el job de ML (no filtrar en el loader).
- **Files de partida:** [services/analytics/scoring_signals.py](../services/analytics/scoring_signals.py), [services/ml/scoring.py](../services/ml/scoring.py)
- **Riesgo:** bajo — hoy es solo instrumentación; la purga se decide con el dato medido.

### [P3] Ordenar /renovaciones por score de oportunidad en el servidor
- **Área:** web/renovaciones, services/competitive/renovaciones
- **Problema:** La tabla trae `limit=1000` ordenado por `fecha_fin_efectiva ASC` y **reordena en cliente** por el score de oportunidad (`web/src/lib/opportunity-score.ts`: riesgo × importe × urgencia). Con más de 1000 contratos en la ventana, el "top de oportunidades" que ve el usuario es el top de las 1000 primeras por fecha de fin, no del dataset. Es un residuo acotado del ítem de KPIs ya cerrado (los KPIs sí son totales de servidor) y está anotado en la línea con `fdi-allow:large-limit`.
- **Acceptance criteria:**
  - El score se calcula en SQL y `proximas_renovaciones` acepta `order_by=score`, de modo que el top-N mostrado sea el top-N real.
  - Retirar el `fdi-allow:large-limit` de `renovaciones/page.tsx`.
- **Files de partida:** [services/competitive/renovaciones.py](../services/competitive/renovaciones.py), [web/src/lib/opportunity-score.ts](../web/src/lib/opportunity-score.ts), [web/src/app/(dashboard)/renovaciones/page.tsx](<../web/src/app/(dashboard)/renovaciones/page.tsx>)
- **Riesgo:** bajo — la fórmula ya está escrita y es determinista; portarla a SQL es mecánico y el eval es comparar ambos órdenes sobre el mismo dataset.

### [P3] Scroll edge effects en vez de divisores duros bajo el chrome flotante
- **Área:** web/src/components/layout
- **Problema:** el chrome flotante es `tf-glass` (translúcido, `position: sticky`) y delimita con un `border-b` fijo, en vez del "scroll edge effect" que pide apple-design §12: un fade/máscara activado por scroll, solo donde el contenido realmente pasa por debajo. Hallazgo F11 de la revisión de las skills de Emil Kowalski (2026-07-25); no bloqueante, es refinamiento visual.
- **⚠️ Este ítem citaba tres ficheros que ya no existen.** Nombraba `top-nav.tsx`, `kpi-bar.tsx` y `global-filter-bar.tsx`; el rediseño de la consola (2026-08-13, ver [docs/redesign/](redesign/)) los sustituyó. El chrome vigente es `console-frame.tsx`, `console-rail.tsx`, `space-shell.tsx`, `scope-bar.tsx`, `dashboard-shell.tsx` y `page-header.tsx`. Corregido el 2026-08-18 — un ítem que apunta a ficheros borrados hace que quien lo coja empiece por un callejón sin salida.
- **Progreso 2026-08-18:** existe `web/src/components/layout/scroll-edge.tsx` con la primitiva (sentinel + `IntersectionObserver`, `prefers-reduced-motion` respetado) y 14 tests. Queda cablearla en el resto de superficies con borde duro.
- **Acceptance criteria:**
  - El borde duro se sustituye por una máscara/gradiente que aparece solo cuando hay contenido scrolleado debajo.
  - Sin borde visible cuando el contenido está en el tope (`scrollY === 0`).
- **Files de partida:** [web/src/components/layout/scroll-edge.tsx](../web/src/components/layout/scroll-edge.tsx), [web/src/components/layout/console-frame.tsx](../web/src/components/layout/console-frame.tsx), [web/src/components/layout/scope-bar.tsx](../web/src/components/layout/scope-bar.tsx)
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

### [P3] Entorno de staging

- **Área:** render.yaml, infraestructura (acción del usuario)
- **Problema:** `render.yaml` define tres servicios, todos en `frankfurt`, ninguno de staging: el primer entorno donde un cambio se ejecuta contra infraestructura real es producción. `deploy.yml` verifica el deploy, pero verificar no sustituye a tener dónde probar.
- **Acceptance criteria (decisión del usuario, con coste asociado):**
  - Decidir si se añade un servicio de staging apuntando a una BD de staging, y si `deploy.yml` despliega allí primero.
- **Files de partida:** [render.yaml](../render.yaml), [.github/workflows/deploy.yml](../.github/workflows/deploy.yml)
- **Relación:** la otra mitad de este ítem —el `plan: free` de la API— se separó el 2026-08-27 y subió a P1, porque contradice un SLO escrito y eso no es un nice-to-have. Se decide con coste, igual que ésta.
- **Riesgo:** bajo técnico, con coste económico — por eso es decisión del usuario.

---

## Cerrados

- [2026-08-18] **P1: seis queries analíticas de `db/` contaban dos veces los contratos
  duplicados entre fuentes** — `tests/test_dedup_guardrail.py` existe para impedir exactamente
  eso, pero **solo escaneaba `services/competitive` y `services/ml`**. Las olas del ratchet
  TID251 llevan meses moviendo SQL analítico a `db/` (ADR-022) y, al moverlo, lo sacaban del
  radio del escáner: sin fallo, sin aviso, y con el commit de la migración saliendo verde. Es
  un guardrail que se desactivaba solo, por el mecanismo mismo del refactor que el backlog
  promueve. Al ampliar el escáner aparecieron 9 funciones sin la cláusula. Dos son exentas por
  diseño (`list_paginated` es CRUD, y `find_publicacion_posterior_a_adjudicacion` busca
  anomalías: deduplicar escondería lo que va a buscar). Una era **falso positivo del propio
  escáner** (`ml_dataset.licitaciones_abiertas` sí deduplica, con la subconsulta escrita
  inline). Las seis restantes eran deuda real, y las dos peores estaban en el camino de las
  métricas que se publican: `load_for_competitors`, que alimenta la cuota de mercado y el HHI
  de `services/analytics/competitors.py` —y se verificó que ese módulo **tampoco** deduplica en
  pandas—, y `load_licitadores`, el ranking de licitadores. Las otras cuatro son los KPIs de
  UTE. En esas cuatro la cláusula se sembró en `_adj_filter_conditions`, el helper que las
  cuatro comparten, para que no se pueda olvidar en la quinta.
  El escáner ahora lleva una lista explícita de módulos de `db/` (`_SCANNED_FILES`) que **cada
  ola futura del ratchet debe ampliar en el mismo cambio que crea el módulo**, y reconoce las
  tres formas legítimas de aportar el dedupe: la llamada al helper, la constante de módulo (el
  idioma de `db/`, que evita importar hacia arriba) y la subconsulta inline. `_PENDIENTES_MAX`
  queda en 0.
  `tests/test_adjudicaciones_dedupe_sql.py` (19 tests, sin BD) fija la composición del SQL en
  la frontera: que la cláusula aparece con filtros y sin ellos, que el `WHERE` queda bien
  formado en ambos caminos, que apunta a `a.licitacion_id` y no a `l.id_externo` —con el LEFT
  JOIN, la columna de la derecha habría descartado filas válidas por `NULL NOT IN`— y, sobre
  todo, **que los `%s` siguen cuadrando con los parámetros**: sembrar una condición en un
  constructor de `WHERE` desalinea los valores en silencio si la condición lleva placeholder, y
  eso no da error, da resultados incorrectos.
  **Lo que no se pudo hacer aquí:** medir el delta. La sesión no tenía Postgres, así que no hay
  número de cuánto bajan la cuota y el ranking al dejar de contar duplicados. Conviene mirarlo
  en el primer deploy: es la magnitud de lo que llevaban inflado.

- [2026-08-08] **P1: el trabajo bloqueante sale del event loop, y un ratchet impide que vuelva** —
  La API es async pero toda la persistencia es síncrona, así que un `async def` que llamaba directo
  a `db.*`/`services.*` ejecutaba ese trabajo **sobre el event loop**: mientras duraba, ningún
  endpoint del proceso respondía. Ninguna herramienta del repo veía la clase (ruff y mypy no
  modelan qué bloquea, y los tests funcionales pasan igual — un handler bloqueante da la respuesta
  correcta, solo que parando el proceso). Los peores casos eran `dual_auth.require_any_auth` y
  `auth._session_principal` (dependencias de casi toda la superficie autenticada, 1 y 3 viajes a BD
  por request), `auth.login`/`register` (seis viajes más argon2, caro por diseño),
  `exports.download_export` (50k filas + reportlab) y `security.verify_audit_integrity` (HMAC fila
  a fila sobre una tabla que solo crece). Los 22 handlers migran al idioma que ya usaba
  `watchlist_rules.post_rule`: el trabajo síncrono en una función anidada y un solo
  `await run_db(...)`, conservando el span OTEL `db.query`.
  `tests/test_async_handlers_no_blocking_io.py` lo congela con allowlist **vacía** (el barrido no
  dejó deuda) y se verificó que detecta una regresión inyectada. De paso, `download_export` empuja
  `tecnologia`/`fecha_desde`/`fecha_hasta` a la query: antes el LIMIT se gastaba en filas que luego
  se descartaban en Python, así que una exportación filtrada podía salir corta. Commits `8f3e7b9`,
  `fa383e5`.

- [2026-08-08] **P1: `/health` responde aunque una dependencia esté colgada** — Los tres sondeos no
  tenían techo de tiempo: con la BD colgada el endpoint esperaba al `connect_timeout` (10 s) o al
  `statement_timeout` (30 s), más de lo que aguanta el probe de la plataforma, que daba el proceso
  por muerto y lo reiniciaba justo cuando `/health` existía para publicar "degraded". Ahora van
  concurrentes en un task group, cada uno bajo `anyio.fail_after` con
  `HEALTH_CHECK_TIMEOUT_SECONDS` (default 5 s). Commit `377b844`.

- [2026-08-08] **P1: `POST /licitaciones/{id}/resumen` alcanzable para ids con `/`** — Usaba el
  conversor por defecto (`[^/]+`) mientras sus ocho rutas hermanas usan `{...:path}`. Los
  expedientes PLACSP con barra en el id (`PA-S 2026/000058`) recibían 404 antes de entrar al
  handler: el resumen ejecutivo era inalcanzable para ellos, en silencio. Commit `fa383e5`.

- [2026-08-08] **P1: `INSERT … RETURNING id` en vez del `lastrowid` emulado** — El adaptador
  emulaba el id con `SELECT lastval()` en sentencia aparte, que devuelve el último valor de
  **cualquier** secuencia de la sesión: con triggers ya en el schema (v61), un trigger que
  insertara en otra tabla con identity hacía que el caller recibiera un id ajeno **sin ningún
  error**. Los dos call-sites de webhooks eran los más expuestos (de ese id se deriva el secret
  HMAC). Los 5 sitios migran y la propiedad se elimina del adaptador. Commit `187ff9d`.

- [2026-08-08] **P2: un solo poller del centinela SSE por proceso** — Cada cliente conectado
  consultaba `shared.cache_signal` cada 5 s por su cuenta: N clientes = N consultas por intervalo
  compitiendo por el threadpool con el resto de la API. Ahora un `_SignalWatcher` por proceso
  publica el timestamp en memoria y cada cliente lo compara con su checkpoint — exactamente lo que
  evaluaba `check_cache_signal`, pero O(1) en conexiones. Arranca con el primer suscriptor y se
  cancela con el último; el bucle por cliente baja a 1 s (comprobación en memoria), mejorando
  latencia y detección de desconexión sin coste de BD. Commit `b07fd6b`.

- [2026-08-08] **P2: `API_THREADPOOL_TOKENS` parametriza el límite de hilos** — `api/app.py` fijaba
  `total_tokens = 4` sin leer settings; ese pool sirve a los endpoints `def` y a todo `run_db`, así
  que el valor correcto para Render Free era un cuello de botella en cualquier instancia mayor.
  Default 4 (comportamiento idéntico) y warning si supera `DB_POOL_SIZE`. Commit `978b373`.

- [2026-08-08] **P2: primer test para los 3 módulos que ninguno mencionaba** —
  `services/deadline_reminders.py` (las tres ventanas, la distinción deadline/renovación, la
  idempotencia que hace seguro correrlo a diario), `services/rate_limiting.py` (selección de
  backend y los dos caminos de degradación, que deben acabar en BD y nunca en "sin rate limiting")
  y `db/repositories/csp_violations.py` (su contrato defensivo: ni tabla ausente ni BD caída
  propagan al endpoint público). Commit `2ca9174`.

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
