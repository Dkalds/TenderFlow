# Improvement Backlog

Lista viva de mejoras conocidas, priorizadas. **Diseñada para que un agente pueda elegir un ítem y trabajarlo sin pedir contexto extra al usuario.**

## Convenciones

- **Prioridad**: P0 (urgente / bloquea) · P1 (alta) · P2 (media) · P3 (nice-to-have).
- **Riesgo**: bajo (cambio aislado) · medio (afecta varios módulos) · alto (toca core / migra schema / cambia contrato).
- Si añadís un ítem nuevo, copiá la plantilla del final.
- Al cerrarlo, no lo dejes tachado aquí: **movélo entero a la sección _Cerrados_** del final con la fecha y el commit/PR que lo resolvió. Las secciones P1/P2/P3 contienen **solo ítems abiertos**.

## Plan de arquitectura 2026-09 — ejecutado parcialmente

El diagnóstico de arquitecto del 2026-09-02 y su plan por streams están en
[plans/2026-09-plan-arquitectura.md](plans/2026-09-plan-arquitectura.md), con el
estado real de cada ítem en su §8. **Excluye a propósito `backup.yml` y
`restore-drill.yml`** (decisión del usuario del 2026-09-02).

Ítems de ESTE backlog que el plan toca, para que nadie los trabaje dos veces:

| Ítem | Estado tras el plan |
|---|---|
| [P2] `HistGradientBoosting` revienta con una feature todo-NaN | **Cerrado** — el entrenamiento descarta antes del ajuste las columnas sin ningún valor observado, con log y test |
| [P2] `render.yaml` no gobierna el servicio de producción | **Parcial** — la cabecera dice ya qué líneas no describen la realidad y con qué fecha se comprobó; vincular el Blueprint sigue siendo acción del usuario |
| [P2] Migrar las llamadas del frontend al cliente tipado | **Cerrado** — no queda ningún `fetch("/api/…")` crudo fuera de `lib/`, y una regla ESLint impide que vuelva |
| [P3] Vigilar el crecimiento de `predicciones_baja` | **Cerrado** — el job de ML purga por antigüedad, y el consumidor distingue el p50 del modelo del del baseline histórico |
| [P3] F5: refactor de repositories (ratchet TID251) | **Progresa** — la whitelist baja de 32 a 28 archivos; el destino sigue siendo vaciarla |
| [P1] Cobertura de tests de las páginas del frontend | **Parcial** — los pisos por carpeta siguen en pie; el piso de `src/app/**` no llegó a ponerse |
| [P2] Remediación axe: 4 reglas desactivadas | **Abierto** — sin tocar; sigue pendiente empezar por `nested-interactive` |
| [P2] Contrato de paginación común | **Abierto** — el agente que lo tenía asignado murió por límite de sesión |
| [P3] Los dos módulos-dios (`aggregates.py`, `settings.py`) | **Abierto** — sigue vigente la regla oportunista |
| [P3] Unificar la definición de «Calientes» | **Abierto** |
| [P3] Descartar los avisos fantasma de Dependabot | **Abierto** — acción del usuario en GitHub |

Ítems **nuevos** que salen del plan y no estaban aquí: partir las páginas
monolito del dashboard (S5.2), el prefetch en servidor con hidratación (S5.1) y
el grupo de rutas `(privado)` que unifica `Providers`/`Toaster` (S5.9). Los tres
quedan descritos en el plan con su porqué y su riesgo.

## Repaso del 2026-08-27 (auditoría de producto/UX)

Este fichero y [UX_AUDIT.md](UX_AUDIT.md) iban por detrás del código que citaban. Lo que cambió:

- **Cerrado y archivado:** el P1 de los enlaces caducados de PLACSP — entregado entero en `c230e63` (PR #191), no en los tres SHAs que el ítem citaba, que nunca llegaron a `master`. Ficha completa en [el archivo](archive/IMPROVEMENT_BACKLOG_CERRADOS.md).
- **Altas:** dos P1 (allowlist de acceso, `plan: free` frente al SLO) y dos P2 (onboarding de primer uso, experiencia móvil). El de la allowlist nace como **RFC**, no como PR: toca auth y necesita migración.
- **Cifras corregidas** en el P1 de cobertura del frontend: las páginas de 1.000+ líneas que citaba ya no existen.
- **Sigue abierto y requiere acción externa:** el P0 de los backups sin copia remota
  (configuración de infraestructura). El índice del scoring en frío ya existe en
  `v84_lic_universo_cpv_index`; queda medir su efecto tras aplicar la revisión, no
  volver a implementarlo.

---

## P0 — Urgente

### [P0] Verificar en GitHub el backup remoto cifrado y su restore drill
- **Área:** .github/workflows/backup.yml, .github/workflows/restore-drill.yml, GitHub Settings (acción del usuario)
- **Problema:** verificado el 2026-09-01 que `BACKUP_ENCRYPTION_KEY` existe y
  faltan `AWS_ROLE_TO_ASSUME`/`BACKUP_S3_BUCKET`. El código ya no bloquea por
  ello: `backup.yml` sube siempre el dump cifrado como GitHub Artifact (90 días)
  y S3 queda como segunda copia opcional; `restore-drill.yml` descarga el último
  artefacto exitoso cuando no hay S3. Falta que este cambio llegue a GitHub y
  ejecutar ambos workflows: hasta que el drill pase, la recuperación sigue sin
  estar demostrada.
- **Acceptance criteria:**
  - Un run de `backup.yml` en verde y artefacto `db-backup-<run_id>` con sólo
    `*.dump.gpg`.
  - Un run de `restore-drill.yml` en verde sobre ese artefacto.
  - Opcional: `AWS_ROLE_TO_ASSUME` y `BACKUP_S3_BUCKET` configurados juntos para
    una segunda copia S3/R2.
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

---

## P2 — Media

### [P2] La portada cita el tamaño del censo bajo un titular que promete lo contrario
- **Área:** producción (acción del usuario) + web/src/app/(publico)/_components/franja-datos.tsx
- **Problema:** la franja de la portada publica el total del corpus público —medido el 2026-09-03 en producción: 417.182 expedientes— justo encima de una sección titulada «Un radar tecnológico, no un censo de toda la contratación pública». Las dos cosas son honestas por separado: el número sale tal cual de `/publico/sitemap/resumen` (ADR-014) y el titular describe la regla de entrada. Lo que las hace incompatibles es que la migración **v98**, que acota la superficie pública al universo tecnológico, está mergeada y **sin aplicar**: `migrate.yml` es `workflow_dispatch` y el `autoDeploy` de Render no migra. Ver el ítem cerrado del 2026-09-02 en [el archivo](archive/IMPROVEMENT_BACKLOG_CERRADOS.md).
- **Por qué importa más que un número feo:** es la única cifra que la portada aporta como prueba, en un producto que vende confianza en el dato. Un visitante que compruebe los CPV más frecuentes en `/cpv` encuentra reactivos de laboratorio.
- **Acceptance criteria:**
  - `migrate.yml` ejecutado y `alembic current` en v98 (se lee en el log del step "Estado actual del schema").
  - `/publico/hubs` deja de listar CPV ajenos a tecnología.
  - La franja de la portada baja a la cifra del universo tecnológico tras la siguiente revalidación.
  - Search Console verá una caída grande de URLs indexadas: es el objetivo, no un incidente.
- **Riesgo:** medio — el cambio es de datos publicados, no de código.

### [P2] La portada sirve una captura oscura a quien tiene el sistema en claro
- **Área:** web/src/app/(publico)/page.tsx, web/e2e/capturas-landing.spec.ts
- **Problema:** la superficie pública usa `defaultTheme="system"` y no tiene selector de tema, así que un visitante con el sistema en claro ve una página clara con una captura del producto en oscuro incrustada. Las dos imágenes de `_assets/` son las únicas que hay.
- **Cómo empezar:** el trabajo está a medias hecho. `npm run capturas:landing` regenera las capturas desde el seed con el stack levantado; falta añadirle la variante `light` (el spec ya usa `page.emulateMedia({ colorScheme })`, sólo hay que parametrizarlo) y dar a `CapturaProducto` un `<source media="(prefers-color-scheme: dark)">`. No se anticiparon los ficheros claros a propósito: dos `.webp` que ningún import consume son peso muerto.
- **Acceptance criteria:** las dos variantes existen, se sirve una sola por visita (no dos descargas), y el spec de capturas las genera juntas.
- **Files de partida:** [web/e2e/capturas-landing.spec.ts](../web/e2e/capturas-landing.spec.ts), [web/src/app/(publico)/page.tsx](../web/src/app/%28publico%29/page.tsx)
- **Riesgo:** bajo.

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
- **Problema (parcialmente resuelto, ver progreso):** quien entra por primera vez aterriza en `/resumen` con el rail de 14 espacios (`web/src/lib/console-spaces.ts`) y una barra de ámbito ya aplicada. En un producto que vende **confianza en el dato**, un número sin explicar la primera vez que se ve no se lee como preciso: se lee como opaco.
- **Progreso 2026-08-30:** la frase original de este ítem —«no existe onboarding de ningún tipo, cero coincidencias de `onboarding` en todo `web/src`»— **ya era falsa** cuando se auditó: `components/onboarding/` y `resumen/_components/primeros-pasos.tsx` existen desde #226, con los tres pasos derivados del estado real del servidor. Y el criterio del score se cerró con el desglose en el propio Radar (`components/score-desglose.tsx`): el badge abre un `Popover` con las dimensiones que componen la puntuación y una nota de qué mide y qué no. El desglose ya viajaba en `ScoredOpportunity.desglose` y solo se pintaba en el inspector de `/detalle`.
- **Acceptance criteria (lo que queda):**
  - ~~Explicar de dónde sale el score~~ ✅ 2026-08-30.
  - Explicar qué es el ámbito de la `scope-bar` la primera vez.
  - Estados vacíos que enseñen en vez de solo informar: el patrón de "sin resultados" ya existe; lo que falta es que diga qué hacer.
- **Files de partida:** [web/src/lib/console-spaces.ts](../web/src/lib/console-spaces.ts), [web/src/components/layout/console-rail.tsx](../web/src/components/layout/console-rail.tsx)
- **Riesgo:** bajo — aditivo, sin tocar datos; el cuidado está en no fabricar explicaciones que el backend no respalde.

### [P2] La experiencia móvil existe pero nadie la diseñó
- **Área:** web/src/components/layout, web/src/app/(dashboard)
- **Problema:** por debajo de `md` el rail de espacios es `hidden` (`console-rail.tsx:196`) y la única navegación es el drawer del `Sheet` (`console-rail.tsx:242-258`). Eso **ya está cubierto por un test real** (`web/e2e/responsive.spec.ts` a 375×812, sin `.or()` ni condicionales), así que no es un agujero de verificación: es que el contenido que hay detrás del drawer no está pensado para ese ancho — lo que llenan las páginas son tablas densas y grafos. El selector de organización del propio rail sigue además siendo un `<select>` nativo (`console-rail.tsx:125`) mientras el resto de controles son Radix: comportamiento de teclado y de lector distinto.
- **Acceptance criteria:**
  - ✅ **Decidido 2026-09-01:** móvil es consulta y triaje —Radar, ficha,
    watchlist y agenda—, no edición completa de matrices analíticas.
  - ✅ Radar y Agenda tienen presentación propia bajo `md`; el E2E exige que
    los cuatro flujos elegidos no desborden el documento.
  - ✅ El selector de organización usa Radix `Select`, alineado con el resto de
    controles de la consola.
  - Pendiente hasta que CI ejecute el nuevo E2E: confirmar Detalle y Watchlist
    a 375×812 sobre el build de producción.
- **Files de partida:** [web/src/components/layout/console-rail.tsx](../web/src/components/layout/console-rail.tsx), [web/e2e/responsive.spec.ts](../web/e2e/responsive.spec.ts)
- **Riesgo:** bajo — presentación; sin tocar contratos ni datos.

### [P3] Documentar `FRONTEND_URL` y `SENTRY_DSN` en `.env.example`
- **Área:** .env.example
- **Problema:** `render.yaml` las declara y `.env.example` no las documenta, así que no se pueden descubrir leyendo el fichero que existe para eso. `scripts/check_env_parity.py` las lleva anotadas en `_DOCUMENTACION_PENDIENTE` para no bloquear CI; esa lista solo puede encoger. No se arreglaron en el mismo cambio porque tocar `.env*` requiere OK explícito (AGENTS.md §6).
- **Acceptance criteria:** ambas documentadas con un comentario de una línea; entrada retirada de `_DOCUMENTACION_PENDIENTE`; `make check-env-parity` sigue verde.
- **Files de partida:** [.env.example](../.env.example), [scripts/check_env_parity.py](../scripts/check_env_parity.py)
- **Riesgo:** bajo — documentación.

### [P2] Remediación axe pendiente: reactivar las 4 reglas desactivadas del E2E de accesibilidad
- **Área:** web/e2e/accessibility.spec.ts, web/src (radar, detalle, watchlist, mi-pipeline)
- **Problema:** el E2E de axe (WCAG 2.2 AA sobre /login, /resumen, /radar y /detalle) nació exigiendo cero violaciones antes de la remediación, y bloqueaba CI con deuda real: `color-contrast` (textos ≤10.5px con opacidad/tokens tenues en las filas del Radar y el detalle), `nested-interactive` (filas-botón del Radar con botones dentro), `scrollable-region-focusable` y `target-size` (<24px). El 2026-09-01 se acotó el gate con `disableRules([...])` — el resto de WCAG-AA y los checks estructurales (landmarks, lang, skip-link, ids únicos, controles con nombre) siguen bloqueando. Los dos ofensores de /resumen sí se arreglaron en ese momento (hint de `StatCell` sin `/80`, chips de Primeros pasos a texto pleno).
- **Relación:** los dos `test.fixme` de `responsive.spec.ts` (watchlist desborda 274px a 375px; la agenda de /mi-pipeline no tiene fichas móviles) son la misma ola — «móvil es consulta y triaje», decidido 2026-09-01. También los dos `test.fixme` de `critical-workflows.spec.ts`: «seguir una licitación» (el click en «Seguir» dentro de la fila-botón del Radar no registra — consecuencia funcional directa del `nested-interactive`, no solo cosmética) y «exportar el ámbito» (el evento `download` no llega en el Chromium de CI; flujo de descarga por diagnosticar bajo Playwright). Ambos eran estrenos en rojo: el `describe` serial los saltaba mientras fallara el primero.
- **Acceptance criteria:** cada regla se reactiva al remediar sus ofensores; la lista de `disableRules` y los `test.fixme` **solo pueden encoger**. Empezar por `nested-interactive` (estructural, no cosmético: rompe la navegación por teclado en el Radar).
- **Files de partida:** [web/e2e/accessibility.spec.ts](../web/e2e/accessibility.spec.ts), [web/e2e/responsive.spec.ts](../web/e2e/responsive.spec.ts), [docs/UX_AUDIT.md](UX_AUDIT.md)
- **Riesgo:** bajo — reactivar una regla sin remediar la pone en rojo en el PR, no en master.

### [P2] Golden set de extracción de fichas: la calidad de la ficha no se mide
- **Área:** tests/eval, services/rag/fact_sheet.py
- **Problema:** el retrieval tiene eval con ratchet (`tests/eval/test_eval_rag.py`, MRR ≥ 0.65); la extracción de fichas y el resumen IA no tienen ninguno. La ficha ya tiene mecánica de validación dura (citas contra texto persistido), pero nadie mide precisión/recall por familia: un cambio de prompt, de modelo o del selector de páginas puede degradar la extracción sin que nada salte. El feedback de usuario (evento `asistente_feedback`, 2026-09-01) da señal débil; el eval da la red fuerte. Esto además **bloquea** la unificación del selector de páginas de la ficha con el retrieval pgvector (ítem siguiente): refactorizar ese selector sin eval es volar a ciegas.
- **Acceptance criteria:**
  - ~10 pliegos reales etiquetados a mano (lotes, criterios con pesos, solvencias, ANS, certificaciones) como fixture versionado.
  - Eval que mida precisión/recall por familia contra ese set, con umbral mínimo ratcheado al valor medido, mismo patrón que `MRR_MIN`.
- **Files de partida:** [tests/eval/test_eval_rag.py](../tests/eval/test_eval_rag.py), [services/rag/fact_sheet.py](../services/rag/fact_sheet.py)
- **Riesgo:** bajo en código; el coste real es el etiquetado manual (decisión/tiempo del mantenedor).

### [P2] Unificar la selección de páginas de la ficha con el retrieval pgvector
- **Área:** services/rag/fact_sheet.py, services/rag/context.py
- **Problema:** conviven dos nociones de "texto relevante del pliego": la ficha puntúa páginas con términos hardcodeados (`_TOPIC_TERMS`/`_TECH_TERMS`, con footguns documentados en el propio fichero) y el chat/resumen rankea chunks (desde 2026-09-01, vía pgvector con fallback Python). Dos selectores, dos presupuestos, dos mantenimientos. La convergencia natural: seleccionar páginas de la ficha con queries fijas por familia ("criterios de adjudicación", "solvencia económica"…) contra los embeddings persistidos, y retirar las listas de términos.
- **Por qué NO se hizo en el cambio del 2026-09-01:** el selector actual está batallado y la extracción no tiene eval (ítem anterior). Cambiar qué páginas ve el LLM sin poder medir el efecto sobre la ficha es exactamente el tipo de regresión silenciosa que este backlog existe para evitar. Orden correcto: primero el golden set, después este refactor medido contra él.
- **Acceptance criteria:** un único camino de selección de contexto de pliegos parametrizado por caso de uso; `_TOPIC_TERMS`/`_TECH_TERMS` retirados; el eval de extracción igual o mejor que el baseline medido.
- **Files de partida:** [services/rag/fact_sheet.py](../services/rag/fact_sheet.py), [services/rag/context.py](../services/rag/context.py), [db/repositories/documentos.py](../db/repositories/documentos.py)
- **Riesgo:** medio — toca el camino que produce el dato más confiable del producto; por eso va detrás del eval.

### [P2] Cada re-ingesta nulea las cuatro columnas ML, y `tech_signal_merge` lo cura a ciegas cada 4h
- **Área:** db/upsert.py, scheduler/pipeline_runs.py, services/tech_signal.py
- **Problema:** `_LIC_UPDATES` genera `k=excluded.k` para todos los campos salvo los cuatro de `_LIC_COALESCE_UPDATE_FIELDS` (`fecha_limite`, `procedimiento`, `tramitacion`, `peso_precio_pct`). `ml_proba`, `ml_tecnologias`, `ml_proba_max` y `ml_tech_principal` **no** están, así que cada re-ingesta de un expediente las pisa con lo que trajo el parser — NULL siempre que el proceso de ingesta no tenga clasificador cargado. `tech_signal_merge` existe para sanar eso, pero corre `merge_doc_signals()` **sin ids**: un barrido de la tabla entera (72.235 filas en `licitacion_tecnologia_score`, medido 2026-09-03) cada 4 h, incluso en las pasadas que no ingirieron nada — y `atom_live` reporta `entries_collected: 0` en la gran mayoría de ellas. La forma incremental ya existe y ya se usa desde `scheduler/jobs/documentos_embeddings.py`.
- **Por qué NO se hizo con el arreglo de la descarga de modelos (2026-09-03):** añadir esas cuatro columnas al `COALESCE` cambia la semántica de escritura de ~700k filas, e impediría además que un re-scoring legítimo limpie un valor viejo. Es una decisión de contrato de datos, no un fix de transporte; bundlearla habría hecho irrevisable el diff del bug.
- **Acceptance criteria:**
  - Decidido y escrito si el clobber se corta en origen (COALESCE) o se sigue sanando aguas abajo.
  - Si se mantiene el merge: el carril diario le pasa los `licitacion_ids` que la pasada tocó, y el barrido completo baja a cadencia diaria (`_run_periodic`).
  - El docstring de `_run_tech_signal_merge` deja de citar solo `precompute_ml_tecnologias` como fuente del clobber.
- **Files de partida:** [db/upsert.py](../db/upsert.py) (`_LIC_COALESCE_UPDATE_FIELDS`), [scheduler/pipeline_runs.py](../scheduler/pipeline_runs.py) (`_run_tech_signal_merge`), [services/tech_signal.py](../services/tech_signal.py) (`merge_doc_signals`)
- **Riesgo:** medio — toca el camino de escritura de la tabla principal.

### [P2] El corpus de PSCP ahoga el dataset del clasificador SAP: no se puede reentrenar, y el modelo servido no discrimina
- **Área:** scraper/ml_training.py (`train_from_db`), scraper/connectors/pscp.py, scraper/ml_pipeline.py (`validate_training_data`)
- **Problema:** `train_from_db` construye el dataset con un `SELECT … FROM licitaciones` **sin filtro de fuente**, y la etiqueta es «`raw_keywords` no vacío OR `tecnologia` no vacía». Medido contra producción el 2026-09-04:

  | fuente | filas | positivos | % |
  |---|---|---|---|
  | **pscp** | 683.076 | 3.113 | **0,46%** |
  | placsp | 6.853 | 4.412 | 64% |
  | bulk_* | 13.095 | 376 | 2,9% |
  | ted | 2.015 | 140 | 6,9% |
  | **total** | **705.094** | **8.041** | **1,14%** |

  Dos consecuencias, las dos verificadas:
  1. **No se puede reentrenar.** `validate_training_data` exige ≥5% de clase minoritaria y aborta con `Minority class is only 1.1% of data`. El run [33855421538](https://github.com/Dkalds/TenderFlow/actions/runs/33855421538) (2026-09-04) murió ahí. El gate hizo su trabajo: no se publicó nada.
  2. **El modelo servido no discrimina sobre esa población.** El de mayo se entrenó cuando el corpus eran ~4k filas de PLACSP con 64% de positivos. Hoy puntúa 683k registros de PSCP que nunca vio y da **90,64% del corpus por encima del umbral** (0,4657), con 42% de las filas en la banda 0,9-1,0. Un binario que dice «SAP» a 9 de cada 10 es una constante, no un clasificador.

  Esto salió a la luz al arreglar la descarga de modelos (#263): hasta entonces el 96% de las filas tenía `ml_proba` a NULL y no había con qué verlo.
- **La bifurcación (hay que elegir, no es solo trabajo):**
  1. **Acotar la población de entrenamiento** por fuente. PLACSP + bulk + TED son 21.963 filas con 4.928 positivos = **22,4%**, muy por encima del suelo: el entrenamiento saldría hoy. Contrapartida: el modelo aprendería de una población distinta de la que puntúa, que es una forma nueva del mismo problema.
  2. **Arreglar el etiquetado de PSCP**, si esas 683k filas deberían llevar `tecnologia`/`raw_keywords` y no las llevan. Sería un bug de conector, y haría innecesaria la opción 1.
  3. **Aceptar** y dejar el modelo de mayo, asumiendo que su score no informa sobre PSCP.
- **Orden sugerido:** mirar primero por qué las filas de PSCP no llevan `tecnologia`. Si es un bug de conector, la opción 2 resuelve las dos consecuencias a la vez; si es correcto (el corpus de PSCP realmente es 99,5% no-TI), entonces la pregunta de verdad es por qué se ingiere entero, y eso conecta con la «contaminación PSCP» de la auditoría de 2026-08.
- **Files de partida:** [scraper/ml_training.py](../scraper/ml_training.py) (`train_from_db`, la query y la etiqueta), [scraper/ml_pipeline.py](../scraper/ml_pipeline.py) (`validate_training_data`), [scraper/connectors/pscp.py](../scraper/connectors/pscp.py)
- **Relación:** bloquea el P1 del golden set (ampliarlo no sirve de nada si el dataset de entrenamiento está ahogado) y explica por qué `model_versions` no tiene ninguna fila de `sap_classifier`.
- **Riesgo:** medio — cambiar la población de entrenamiento cambia qué aprende el clasificador que decide el rescate ML en ingesta.

### [P2] `baja_model` v2 y `retencion_model` v1 están entrenados y publicados, pero nadie puede decidir si activarlos
- **Área:** db/model_registry.py, services/ml/baja_model.py, services/ml/calibration.py (acción del usuario)
- **Problema:** desde el 2026-09-03 el reentrenamiento vuelve a completar y sus artefactos están en la Release, pero las tres filas de `model_versions` siguen con `is_active = 0`, así que `ml-scoring.yml` sirve baseline **en verde**. La activación es decisión humana por diseño (`train-predictivos.yml`: *"salvo `ML_PRED_AUTO_ACTIVATE`"*), y el problema es que **las métricas registradas no permiten tomarla**:
  - `baja_model` v2 mejora al baseline un **3,3%** (`mae_p50` 0.12494 vs `mae_baseline` 0.12999, o sea 0.005), pero su propia dispersión entre folds es **`mae_p50_std_folds` = 0.01287**, dos veces y media esa mejora. Es indistinguible de ruido con la evidencia que hay.
  - `retencion_model` v1 no registra **ninguna** métrica de baseline (`pr_auc` 0.2453 sobre prevalencia 0.1099, `ece` 0.054): no hay contra qué compararlo.
  - `baja_model` v1 (2026-08-05) sí registra una mejora del 17,8%, pero su ventana de validación dice `valid_hasta: "2032-06-23"` —una fecha futura, o sea basura— y se entrenó antes del arreglo del rolling origin y del filtro de fechas. No es comparable, y su artefacto ya no está en la Release.
- **Por qué no se activó al arreglar la descarga (2026-09-03):** activar cambia lo que ve producción, no hay gate automático como el de `services/ml/promotion.py` del SAP, y no hay medición posterior que detecte una regresión. Activar sobre una mejora menor que la varianza es activar sobre ruido.
- **Acceptance criteria:**
  - Un criterio de promoción escrito para los predictivos, del mismo tipo que el del clasificador SAP: qué margen sobre el baseline y con qué dispersión se considera suficiente.
  - `retencion_model` registra una métrica de baseline comparable (el ranking trivial por prevalencia o por antigüedad del contrato).
  - Decidido y ejecutado: activar o descartar, con el número que lo justifica anotado en `notes` de `model_versions`.
- **Files de partida:** [db/model_registry.py](../db/model_registry.py), [services/ml/baja_model.py](../services/ml/baja_model.py), [services/ml/promotion.py](../services/ml/promotion.py) (el gate del SAP, como referencia), [.github/workflows/train-predictivos.yml](../.github/workflows/train-predictivos.yml)
- **Riesgo:** medio — activar cambia lo que sirve `predicciones_baja` sin red que lo detecte.

### [P3] Las 47 adjudicaciones con fecha imposible siguen anclando filas de entrenamiento
- **Área:** services/ml/features.py, db/repositories/ml_dataset.py, scraper/connectors/pscp.py
- **Problema:** el #262 filtra en `_fecha_opt` los años de menos de cuatro cifras (`0019-12-10` del expediente `19/002/5-2`, `0202-02-27` de PSCP), que es lo que rompía el round-trip de `%Y`. Pero de las **47 filas** de `adjudicaciones` con `fecha_adjudicacion` imposible —medidas contra producción el 2026-09-03— la mayoría son `1899-12-30`: el cero de la epoch de Excel, o sea como PSCP exporta una celda vacía. Esas pasan el filtro, porque tienen cuatro cifras y parsean bien. Y el ancla del dataset es `LEAST(fecha_publicacion, fecha_adjudicacion)`, así que ganan: la fila entra en el train de **todos** los folds con los acumuladores históricos vacíos, y su adjudicación los alimenta como si precediera a todo el histórico.
- **Por qué no se subió el umbral con el #262:** el `_ANIO_MINIMO = 1000` está justificado por la asimetría de `%Y` entre `strptime` y `strftime`, que es un hecho del parser y no admite discusión. Un umbral de *plausibilidad* (1990, 2008…) es una afirmación distinta —sobre los datos, no sobre el formato— y merece decidirse aparte en vez de colarse dentro de una constante que hoy significa otra cosa.
- **Acceptance criteria:**
  - Decidido dónde se corta: el conector de PSCP (que es quien genera el `1899-12-30`), el parser, o el SQL del dataset.
  - Las 47 filas dejan de anclar filas de entrenamiento, verificado con la misma query que las midió.
- **Files de partida:** [services/ml/features.py](../services/ml/features.py) (`_fecha_opt`), [db/repositories/ml_dataset.py](../db/repositories/ml_dataset.py) (`fecha_anchor`), [scraper/connectors/pscp.py](../scraper/connectors/pscp.py)
- **Riesgo:** bajo — son 47 filas de ~691k adjudicaciones; el impacto es de calidad de dataset, no de disponibilidad.

### [P3] Un solo transporte para bajar assets de la Release
- **Área:** shared/model_artifacts.py, shared/release_assets.py
- **Problema:** conviven dos implementaciones de "bajar un asset de la última Release". `shared/release_assets.py` (2026-09-03) va sobre HTTPS pinned con allowlist por salto; `shared/model_artifacts.py::_download_release_asset` usa `requests.get(browser_download_url)` a pelo, que sigue redirects sin validar el destino y sin DNS pinning. La segunda funciona —de hecho es la única que nunca se rompió— pero tiene controles más débiles que el resto de las salidas del repo, y dos implementaciones divergentes del mismo salto es cómo se cuelan las regresiones asimétricas.
- **Por qué NO se hizo en el mismo cambio:** era el único camino de descarga que funcionaba; tocarlo mientras se arreglaba el otro habría dejado el sistema sin ninguno si el refactor fallaba.
- **Acceptance criteria:** `_download_release_asset` delega en `shared.release_assets`, conservando la verificación contra el sha256 del registry; los tests de `shared/model_artifacts.py` siguen verdes.
- **Files de partida:** [shared/model_artifacts.py](../shared/model_artifacts.py), [shared/release_assets.py](../shared/release_assets.py)
- **Riesgo:** bajo — el fallback a baseline ya está cubierto y testeado.

---

## P3 — Nice to have

### [P3] Pre-generar el resumen IA nocturno para licitaciones calientes
- **Área:** scheduler/jobs, api/routes/ask.py
- **Problema:** desde 2026-09-01 el resumen se cachea por firma de estado (documentos + ficha + metadatos), pero la primera visita de cada licitación sigue pagando latencia completa de proveedor. El cron nocturno podría calentar el caché para el subconjunto que la gente abre (vigiladas, banda alta de score, publicadas ese día) y el detalle abriría con el resumen ya puesto.
- **Acceptance criteria:** fase opcional del job nocturno (gated por setting, mismo patrón que `PLIEGO_FACTS_ENABLED`) que genera el resumen para N licitaciones priorizadas si no hay entrada vigente; presupuesto LLM respetado (BudgetGuard ya cuenta este gasto).
- **Files de partida:** [api/routes/ask.py](../api/routes/ask.py), [scheduler/jobs/documentos_embeddings.py](../scheduler/jobs/documentos_embeddings.py)
- **Riesgo:** bajo — reutiliza el caché y el breaker de coste existentes; el riesgo es gasto LLM, acotado por el propio guard.

### [P3] Descartar los avisos fantasma de Dependabot (manifest `uv.lock` inexistente)
- **Área:** GitHub Security (acción del usuario), .github/dependabot.yml
- **Problema:** 37 de los 38 avisos abiertos apuntan a un `uv.lock` que se borró de `master` en `cc096fb` (2026-05-31). El grafo de dependencias de GitHub conservó una instantánea de ese fichero y **sigue emitiendo avisos nuevos contra ella** — los abiertos van del 2026-07-13 al 2026-08-07, todos posteriores al borrado. La prueba está en el SBOM, que lista a la vez los pines vivos y sus fantasmas (`pillow@12.3.0` ×2 junto a `pillow@12.2.0`; `cryptography@50.0.0` ×2 junto a `46.0.7`), y en el trío del 2026-08-03 sobre `GHSA-g6cj-pr64-35w5`: #82 y #83 (manifiestos vivos) se cerraron el mismo día; #87 (`uv.lock`) sigue abierto y no puede cerrarse nunca.
- **Cómo triar (corregido 2026-08-30):** **no** basta con filtrar por `manifest_path`, y sobre todo no debe convertirse en una regla de auto-descarte. GitHub atribuye mal ese campo: los tres avisos de `cryptography` (#87–#89) salen etiquetados como `uv.lock` pese a que ese paquete **nunca** estuvo en ese fichero. Una regla que descarte por `manifest_path: uv.lock` acabaría tapando en silencio un aviso real de `requirements.txt`. El criterio que sí decide es el pin vivo: comparar `first_patched_version` contra `requirements.txt` / `requirements-dev.txt` / `web/package-lock.json`, aviso por aviso.
- **Acceptance criteria:** los 37 descartados con motivo (`not_used` los 18 de GitPython, que no está en ningún manifiesto; `inaccurate` el resto, cuyo pin vivo ya está parcheado); el listado refleja solo manifiestos reales. La cura de fondo —que el grafo deje de ver `uv.lock`— exige forzar un re-parse del path o abrir ticket a GitHub Support; el toggle del dependency graph no existe en repos públicos.
- **Files de partida:** [.github/dependabot.yml](../.github/dependabot.yml)
- **Riesgo:** bajo — no toca código; el cuidado está en verificar cada aviso contra el pin vivo en vez de contra el nombre del manifiesto.

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

- [2026-09-01] **Revisión integral de la IA del detalle de licitación (10 mejoras en un
  cambio)** — salida de la auditoría de arquitecto del asistente IA. Lo que cambió:
  (1) el extracto de `descripcion` es ahora por modo (`llm/prompts.py::_EXCERPT_CHARS_BY_MODE`):
  el resumen ejecutivo veía **300 chars** del anuncio con 16k de presupuesto sin usar;
  (2) la neutralización anti-inyección cubre el bloque de contexto entero — `titulo` y
  `descripcion` también son texto scrapeado y podían cerrar `</fuentes_no_confiables>`;
  (3) los prompts internos (extraction/clasificacion/resumen) dejan de viajar por el límite
  de usuario de 2000 chars (`MAX_INTERNAL_QUESTION_LEN=12k`) — la causa raíz del incidente
  v3 de la ficha; (4) cadena de fallback de proveedor (`FALLBACK_MODELS`): un modelo que
  falla o devuelve vacío ANTES del primer token pasa al siguiente con API key, con métrica
  `llm_fallback_total` — mitiga el patrón deepseek-v4-pro (6 días caído en silencio);
  (5) canary diario del catálogo NIM (`scheduler/jobs/llm_models_canary.py`, paso canónico
  `llm_models_canary`) que convierte el próximo EOL en un email en vez de en un 410 mudo;
  (6) el serving del chat/resumen usa los embeddings pgvector persistidos
  (`DocumentosRepository.search_chunks_by_embedding`, `ORDER BY embedding <=>`) cuando el
  motor está disponible, con el camino Python previo como fallback — hasta ahora el job
  nocturno pagaba embeddings que ninguna request consultaba, y sin el extra instalado el
  "ranking semántico" real de producción era overlap de substrings; (7) el resumen se
  cachea por firma de estado (documentos + ficha + metadatos, `shared/cache`, TTL 7d) con
  `force` para regenerar y `cached` en `resumen_meta` — sin migración a propósito (gate §6);
  (8) la ficha verificada entra como contexto priorizado del resumen (chunk «ficha
  estructurada verificada» + instrucción en el system prompt); (9) `/ask` emite el evento
  aditivo `ask_meta` con el ámbito EFECTIVO y la UI avisa cuando la respuesta degradó al
  corpus — antes ese fallback era silencioso en el detalle; (10) «Extraer ficha» pasa a
  background (`extract-async` + polling de `/estado`, flag `running` en cache y no en el
  CHECK de la tabla), las citas de la ficha resuelven a `filename · página` con deeplink
  `#page=N` al PDF, la confianza autoinformada se presenta como ordinal, y nace el evento
  `asistente_feedback` (👍/👎 en chat, resumen y ficha). Diferido con criterio: golden set
  de extracción y unificación del selector de páginas (ítems P2 nuevos), pre-generación
  nocturna del resumen (P3). **Verificación:** ruff y mypy strict en verde; suite unit
  completa en verde salvo dos fallos preexistentes de trabajo sin commitear ajeno a este
  cambio (`auth.py::confirm_password_reset` en el checker de blocking-IO y el test de
  notificación de solicitudes); contrato OpenAPI e invariantes frontend OK; tsc/eslint/
  vitest del frontend en verde. Los tests de integración (Postgres) NO se ejecutaron en
  esta sesión — sin BD local — y quedan para CI.

- [2026-08-30] **P2: extraer las vistas de `/ops` a componentes compartidos** — ya estaba
  hecho y el ítem seguía abierto describiendo el estado anterior. `ops/page.tsx` importa hoy
  seis `_components/<x>-view.tsx` y ninguna `page.tsx`; su propio docstring documenta el
  cambio. Se cierra al detectarlo en la auditoría del 2026-08-29: un ítem cuya premisa el
  código desmiente hace que quien lo coja empiece por un callejón sin salida, que es
  exactamente lo que AGENTS.md §5 prohíbe.

- [2026-08-30] **P0: las alertas de reglas de vigilancia no podían dispararse** — el job
  guardaba su cursor como marca de tiempo y lo comparaba como **fecha**, con `>` estricto,
  contra `fecha_publicacion`, que solo tiene día; y adelantaba la ventana en cada evaluación
  hubiera o no coincidencias. Efecto compuesto: en cuanto una regla se evaluaba el día D, todo
  lo publicado ese día quedaba fuera de su ventana **para siempre**. Con el carril diario
  corriendo a las 00:0x UTC —cuando no se ha publicado nada del día todavía— la regla no
  volvía a disparar nunca después de su primera evaluación. Sin excepción, sin log y con sus
  tests en verde, porque todos sembraban el cursor y la publicación en días distintos, que es
  el único caso que funcionaba.
  El corte pasa a inclusivo con dos días de gracia y **quien decide qué es nuevo deja de ser
  la fecha**: es el anti-join contra `user_notifications`
  (`db/repositories/watchlist_rules.py::matches_pendientes`), o sea la misma verdad que ya
  imponía el `UNIQUE(user_key, licitacion_id, type)` de v48 — solo que antes actuaba en el
  INSERT, demasiado tarde para impedir que las filas ya notificadas gastaran el `LIMIT`.
  De paso, una regla que satura el tope deja aviso en vez de perder las coincidencias por
  encima de él. Tres tests nuevos, incluido el del mismo día que faltaba.
  **No verificado:** los tests exigen Postgres y esta sesión no lo tiene.

- [2026-08-30] **P1: el refresco de la vista pública corría antes que cinco de las siete
  fuentes** — `scrape-daily.yml` ejecutaba `run_update --daily`, que ingiere PLACSP *y* corre
  la secuencia canónica entera (KPIs, refresco de `licitaciones_canonicas`, evaluación de
  reglas, digests), y solo entonces lanzaba TED, Galicia, Euskadi, adjudicaciones vigiladas,
  PSCP y TACRC. Su corpus del ciclo no entraba en la superficie pública, ni en los agregados,
  ni en las alertas hasta cuatro horas después. El contrato escrito en
  `db/repositories/publico.py` decía «al final de la pasada de ingesta»; era a mitad.
  La pasada se parte en `--fase ingesta` y `--fase cierre` (`run_post_ingestion_only`), y el
  cierre es ahora el último step del workflow. Sin `continue-on-error`: un cierre roto sí debe
  poner el job en rojo, porque es donde viven el refresco y las alertas.

- [2026-08-30] **P1: un fallo del clustering congelaba la superficie pública en silencio** —
  `run_aggregates_precompute` declaraba en su docstring que el refresco iba aparte «por si el
  clustering fallara» y metía las dos cosas en el mismo `try`, con los dos caminos que de
  verdad pueden caer —una lectura de 50.000 filas y un DELETE con inserciones por lotes— por
  delante del refresco. El resultado era el sitio público servido sobre el último corpus
  bueno: cifras coherentes entre sí, viejas, y sin nada que lo delatara. Ahora son dos `try`
  independientes con estado `partial`, y el healthcheck vigila la vista (`canonicas_frescas`,
  `canonicas_tamano`) leyendo el evento `mv_canonicas_refresh` de `ops_events` — la única
  señal que cruza del plano efímero de Actions. NO se añadió regla de Prometheus, y está
  escrito por qué en `alert_rules.yml`: el scheduler no es scrapeable, sería una alerta muerta.

- [2026-08-30] **P1: métricas de cobertura desconocida pintadas como 0 %** — `/resumen` se
  abstenía de publicar `pct_oferta_unica` sin cobertura suficiente y `/competidores`, un clic
  más allá, publicaba la misma magnitud sin acotar; el gráfico de posicionamiento convertía
  los nulos en `0 %`, presentando a una empresa sin dato de ofertantes como la más disputada
  del mercado. El helper sale a `lib/cobertura.ts` y se aplica en las dos superficies. El
  guard `check_frontend_invariants.py` gana la categoría `nulo-a-cero`, que encontró **18**
  ocurrencias: se corrigieron las que se pintan y se justificaron en su línea las que son
  denominador o clave de orden.

- [2026-08-30] **P1: la superficie pública perdía su telemetría en el proxy de borde** —
  `PUBLIC_PREFIXES` de `web/src/proxy.ts` no eximía `/_vercel`, así que las peticiones a
  `/_vercel/insights/*` y `/_vercel/speed-insights/*` sin cookie de sesión —o sea todas las de
  la superficie anónima— recibían un 307 a `/login`. Se perdían las páginas vistas de las URLs
  indexables y los dos eventos que miden la conversión del embudo. Dentro del dashboard no se
  notaba porque allí siempre hay sesión, que es lo que lo hacía invisible desde dentro del
  producto. Con él se añade la primera suite de `proxy.ts` (31 casos): rutas públicas y
  privadas, la trampa del prefijo `/` que el propio fichero documentaba sin red debajo, y las
  dos ramas de CSP. **Pendiente de verificar contra producción:** si además el plan de Vercel
  descarta los eventos personalizados (son función de Pro), este arreglo no basta por sí solo.

- [2026-08-30] **P1: el aviso legal declaraba sus propias lagunas en producción** — el sitio
  es indexable y recoge una dirección de correo por consentimiento explícito, y la página
  terminaba con «Pendiente de completar: identificación del responsable del tratamiento y
  domicilio social». Honesto, y no es cumplir: el RGPD (art. 13) y la LSSI-CE (art. 10) exigen
  identificar al responsable en el momento de la recogida. La identidad pasa a `lib/legal.ts`
  y la ausencia **rompe el build de producción** (`next.config.ts`), en vez de hacer
  desaparecer el bloque en silencio. El plazo de conservación deja de ser «no hay ninguno»: se
  publican 24 meses y `scheduler/retention.py` los aplica, con un test que compara el número
  publicado con el que borra el job — si se separan, el aviso pasa a ser una promesa falsa sin
  que falle nada. **Requiere acción del responsable:** cargar las tres variables en Vercel.

- [2026-08-30] **P2: nueve rutas del dashboard sin título de documento** — WCAG 2.2 §2.4.2,
  nivel A. Faltaba en Radar y Oportunidades, las dos pantallas insignia, que heredaban el
  `default` del layout raíz: pestaña, marcador, historial y lector de pantalla decían
  «TenderFlow» en todas. Nueve `layout.tsx`, `generateMetadata` en las dos rutas dinámicas, y
  un test que recorre el árbol para que la décima falle el día que se cree.

- [2026-08-30] **P2: cambiar de espacio no se anunciaba ni movía el foco** — la consola navega
  en cliente entre catorce espacios y el foco se quedaba en el enlace del rail. Las dos piezas
  necesarias ya existían sin usarse: la región `aria-live` única y el `#main-content` con
  `tabIndex={-1}`. Seis líneas en `DashboardShell` y tres tests.

- [2026-08-30] **P2: el guard de superficie pública no alcanzaba al código que la alimenta** —
  `check_public_surface.py` escaneaba `api/routes`, `db/repositories/publico.py` y
  `web/src/app/(publico)`, y dejaba fuera los módulos de `lib/` que componen lo que se publica
  (`jsonld.ts` serializa datos estructurados con `dangerouslySetInnerHTML`). No había fuga:
  había una red con un agujero que se abriría en cuanto alguien extrajera una pieza a `lib/`,
  que es el refactor que el repo promueve — el mismo mecanismo por el que el escáner de
  deduplicación se desactivó solo en 2026-08. Radio ampliado de 23 a 36 ficheros y verificado
  inyectando una fuga temporal en `lib/jsonld.ts`, que el guard detectó.


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
