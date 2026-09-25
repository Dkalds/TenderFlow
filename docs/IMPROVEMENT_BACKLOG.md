# Improvement Backlog

Lista viva de mejoras conocidas, priorizadas. **Diseñada para que un agente pueda elegir un ítem y trabajarlo sin pedir contexto extra al usuario.**

## Convenciones

- **Prioridad**: P0 (urgente / bloquea) · P1 (alta) · P2 (media) · P3 (nice-to-have).
- **Riesgo**: bajo (cambio aislado) · medio (afecta varios módulos) · alto (toca core / migra schema / cambia contrato).
- Si añadís un ítem nuevo, copiá la plantilla del final.
- Al cerrarlo, no lo dejes tachado aquí: **movélo entero a la sección _Cerrados_** del final con la fecha y el commit/PR que lo resolvió. Las secciones P1/P2/P3 contienen **solo ítems abiertos**.

## Plan de funcionalidades 2026-09 — ejecutado casi entero

El plan y sus criterios de aceptación están en
[plans/2026-09-plan-funcionalidades.md](plans/2026-09-plan-funcionalidades.md).
Treinta y ocho funcionalidades en seis recorridos; **treinta y seis con
backend** (F4.6 se desbloqueó el 2026-09-18) y dos descartadas por su propia
decisión (F2.1 y F6.6). Tener backend no es tener pantalla: ver la nota de
abajo.

*Estado (2026-09-19):* el «treinta y seis con backend» era optimista en dos
ítems, comprobado en el código: **F1.4 no tiene backend real** — el scoring
nunca emite `organo_anula_frecuente` (solo existen su texto en
`services/analytics/scoring_explicacion.py` y su rótulo en
`web/src/lib/riesgos.ts`) y no hay tasas precalculadas —, y **F2.8 tiene
backend solo para la tabla** (`POST /licitaciones/comparar`): `/ask` sigue
aceptando un único `id_externo`, así que la pregunta cruzada falta también en
el backend, no solo en la UI.

Lo que **no** se hizo, y por qué:

| Ítem | Estado | Motivo |
|---|---|---|
| F2.1 Hitos del procedimiento | **Descartado por D32** | El spike midió 735 entradas del ATOM en vivo: `OpenTenderEvent` aparece en el **0 %**, muy por debajo del umbral del 30 % que D32 fijaba. Ver [el documento del spike](plans/2026-09-spike-d32-hitos-procedimiento.md). La consecuencia prevista —que la fecha prevista de adjudicación se estime sola— está implementada (F4.4), y `ExpectedAward.metodo` ya admite `hito` para el día que la Plataforma los publique. |
| F4.6 Plantillas de tareas por etapa | **Hecho el 2026-09-18** (rama `worktree-agent-a46c6c93b69b8f96c`) | Se desbloqueó al llegar las tareas C6.1 (v122). Sin migración: plantilla en `plantillas_organizacion` (`tipo='tareas'`), instanciación idempotente por `pursuit_events`, editor en Equipo → Organización. |
| F6.6 Boletín público | **Descartado por D36** | La propuesta de D36 es «no hasta que exista dominio propio (v2 S1.3) y política de privacidad para suscriptores». Ninguna de las dos existe. |

Lo que se hizo **con fallback**, porque su dependencia no está en este árbol
(no hay outbox de eventos, ni maestro de órganos, ni invitaciones de v2):

- **F1.5** guarda la cuenta objetivo en tabla propia con el nombre plegado del
  órgano, que es lo que el plan prevé hasta que llegue C1.2. La columna
  `organo_id` nace ya, nullable, para que ese maestro la rellene sin migración.
- **F5.1–F5.4, F3.4 y F4.3** entregan por los jobs y la campana que ya existen,
  no por el outbox. El catálogo de subtipos de aviso está escrito una sola vez
  (`services/avisos.py`), así que enchufarlo al outbox cuando exista es cambiar
  el productor, no el vocabulario.
- **F3.2** distingue «nosotros perdimos» de «ellos ganaron»: sin el NIF propio
  (v2 S2.1) sólo se puede afirmar lo primero, y la respuesta lo declara. La
  pestaña «Contra mí» lo pinta así desde el 2026-09-18 (UI de F1.2, F3.2,
  F3.3, F5.4 y F5.6 en la rama `worktree-agent-aa4eeee01ef3fbb62`; ver el estado de cada ítem en el plan).
- **F2.3** se entregó sin responsable; desde el 2026-09-18 el responsable es
  el de la tarea C6.1 del documento (rama `worktree-agent-a46c6c93b69b8f96c`).

**«Implementadas» significaba backend.** Varias de las treinta y cinco no
tenían pantalla. En el lado de oportunidades, la UI llegó el 2026-09-18 (rama
`worktree-agent-a46c6c93b69b8f96c`) para F1.6 (aplicar/quitar etiquetas; falta
el filtro en Radar y Detalle), F2.3, F3.1, F4.1 (sin pantalla para editar las
probabilidades), F4.3 (sin «preparar renovación», que no tiene endpoint), F4.4
y F4.6. El estado de cada una está anotado en el plan.

Pantallas que faltaban de lado ficha y superficie pública (2026-09-18, rama
`worktree-agent-ac5d5218d7d3b1f8b`): F2.2, F2.5, F2.6, F2.8, F6.2 y F6.5 ya
tienen UI; el estado por ítem está anotado en el plan. Quedan sin hacer: el
PDF del guion (F2.6, sin ruta en el backend), `/ask` multi-expediente (F2.8;
sin backend ni UI, ver la nota de arriba) y la emisión de `evidencia_abierta` (F2.5). Los E2E nuevos
(`pagina-cita.spec.ts`, bloque de órganos de `seo.spec.ts`) no se ejecutaron
en local.

Ítems de **este** backlog que el plan toca:

| Ítem | Estado tras el plan |
|---|---|
| [P3] Unificar la definición de «Calientes» | **Sin tocar** — sigue abierto |
| [P2] Remediación axe: 4 reglas desactivadas | **Cerrado** el 2026-09-19 — las cuatro reactivadas; ver _Cerrados_ |

Hallazgos nuevos que el plan destapó y ya están corregidos: el
`TIPO_CONTRATO_LABELS` con dos etiquetas desplazadas y cuatro códigos sin
traducir; `list_cursor` comparando `tecnologia` por igualdad sobre una columna
que guarda un CSV; la rama FTS ignorando los filtros; y la consulta de
lead-time contando dos veces los expedientes duplicados.

## Plan de arquitectura 2026-09 — ejecutado parcialmente

El diagnóstico de arquitecto del 2026-09-02 y su plan por streams están en
[plans/2026-09-plan-arquitectura.md](plans/2026-09-plan-arquitectura.md), con el
estado real de cada ítem en su §8. **Excluye a propósito `backup.yml` y
`restore-drill.yml`** (decisión del usuario del 2026-09-02).

Ítems de ESTE backlog que el plan toca, para que nadie los trabaje dos veces:

| Ítem | Estado tras el plan |
|---|---|
| [P2] `HistGradientBoosting` revienta con una feature todo-NaN | **Cerrado y movido** el 2026-09-06 a _Cerrados_ — el entrenamiento descarta antes del ajuste las columnas sin ningún valor observado, con log y test |
| [P2] `render.yaml` no gobierna el servicio de producción | **Parcial** — la decisión se tomó el 2026-09-06 (O0.2 del plan v2: se vincula el Blueprint y `autoDeploy` se apaga); vincular y verificar en el dashboard sigue siendo acción del usuario |
| [P2] Migrar las llamadas del frontend al cliente tipado | **Cerrado y movido** el 2026-09-06 a _Cerrados_ — no queda ningún `fetch("/api/…")` crudo fuera de `lib/`, y una regla ESLint impide que vuelva |
| [P3] Vigilar el crecimiento de `predicciones_baja` | **Cerrado y movido** el 2026-09-06 a _Cerrados_ — el job de ML purga por antigüedad, y el consumidor distingue el p50 del modelo del del baseline histórico |
| [P3] F5: refactor de repositories (ratchet TID251) | **Progresa** — la whitelist baja de 32 a 28 archivos, y a 26 el 2026-09-16 (`kpi_precompute`, `mercado`); el destino sigue siendo vaciarla |
| [P1] Cobertura de tests de las páginas del frontend | **Cerrado y movido** el 2026-09-18 a _Cerrados_ — primera medición local completa; pisos globales y de `src/app/**` subidos a lo medido |
| [P2] Contrato de paginación común | **Cerrado y movido** el 2026-09-18 a _Cerrados_ — dependencia `limit`/`offset` compartida en `api/pagination.py`, primera ola de siete rutas; `trends` ya exponía `group_by` |
| [P2] Remediación axe: 4 reglas desactivadas | **Cerrado y movido** el 2026-09-19 a _Cerrados_ — `nested-interactive` (C7.1), las tres restantes el 2026-09-18 y los rojos que destapó el E2E en `8a424967` y `0fd5082c`; sin `disableRules` ni `fixme` |
| [P3] Los dos módulos-dios (`aggregates.py`, `settings.py`) | **Abierto** — sigue vigente la regla oportunista |
| [P3] Unificar la definición de «Calientes» | **Cerrado y movido** el 2026-09-18 a _Cerrados_ — se mantiene la heurística de importe como «Grandes en plazo», documentada en los DTOs |
| [P3] Descartar los avisos fantasma de Dependabot | **Abierto** — acción del usuario en GitHub; 33 descartados el 2026-08-30 y 8 nuevos desde entonces (2026-09-24) |

Ítems **nuevos** que salen del plan y no estaban aquí: partir las páginas
monolito del dashboard (S5.2), el prefetch en servidor con hidratación (S5.1) y
el grupo de rutas `(privado)` que unifica `Providers`/`Toaster` (S5.9). Los tres
los recoge hoy el ítem de S7 del plan v2, más abajo.

## Plan de arquitectura 2026-09 **v2** — Ola 0 en curso

El sucesor está en
[plans/2026-09-plan-arquitectura-v2.md](plans/2026-09-plan-arquitectura-v2.md)
y es la **fuente única de alcance y criterios** de sus ocho streams: los ítems
`[Ola 1]` de este backlog existen para que la priorización no exija leerlo
entero, y remiten al plan en vez de copiarlo (dos copias del mismo criterio
divergen).

O0.5 se ejecutó el **2026-09-06**: las decisiones D1–D9 y D11–D20 quedan
cerradas con fecha y evidencia en las tablas §3 de los dos planes, y los ítems
que el código ya había resuelto bajan a _Cerrados_. Lo que las tablas cierran es
la **decisión**, no siempre su ejecución: las dos que dependen del dashboard de
Render siguen abiertas como trabajo —D4 la ejecuta O0.2 (y el P2 de `render.yaml`
de más abajo es su mitad de infraestructura) y D5 la ejecuta O0.3—, y los
streams de Ola 1 arrancan con su decisión ya tomada.

**Qué de la Ola 1 entra aquí y qué no.** Hay un ítem `[Ola 1 · Sx]` por cada uno
de los siete streams que no tienen ya sitio en este backlog: S1, S2, S3, S4, S5,
S7 y S8.

**S6 no lleva ítem propio**, y no por olvido: tres de sus cinco subítems ya
tienen entrada aquí y se siguen desde ella —S6.1 desde el P2 «El corpus de PSCP
ahoga el dataset del clasificador SAP», que es el diagnóstico que el propio
subítem del plan cita; S6.3 desde el P1 del golden set; S6.5 desde el P2 del
modelo de baja por lote—, y abrirle un ítem paralelo dejaría dos sitios donde
mirar lo mismo. Los dos que no tienen entrada (S6.2, etiquetas no circulares;
S6.4, criterio de promoción escrito) están en el §5 del plan y son de esfuerzo S.

**Lo que esta sección NO dice es cuánto de la Ola 1 está ya escrito.** Los
streams los están entregando agentes distintos en paralelo mientras se redacta
esto, así que cualquier foto del estado que tomara este fichero nacería
caducada — y un backlog que lista como abierto algo ya cerrado es exactamente la
avería que O0.5 existe para arreglar. Quien manda sobre el estado es el §5 del
plan, donde cada stream anota lo entregado al cerrarse — la misma convención que
la Ola 0 ya usa en su §4. Estos ítems los da de baja la consolidación de la ola,
no una comprobación hecha a mitad de ella.

## Repaso del 2026-08-27 (auditoría de producto/UX)

Este fichero y [UX_AUDIT.md](UX_AUDIT.md) iban por detrás del código que citaban. Lo que cambió:

- **Cerrado y archivado:** el P1 de los enlaces caducados de PLACSP — entregado entero en `c230e63` (PR #191), no en los tres SHAs que el ítem citaba, que nunca llegaron a `master`. Ficha completa en [el archivo](archive/IMPROVEMENT_BACKLOG_CERRADOS.md).
- **Altas:** dos P1 (allowlist de acceso, `plan: free` frente al SLO) y dos P2 (onboarding de primer uso, experiencia móvil). El de la allowlist nace como **RFC**, no como PR: toca auth y necesita migración. *(2026-09-19: los cuatro están resueltos; el del `plan: free` nunca llegó a tener entrada — ver la nota del P3 de staging.)*
- **Cifras corregidas** en el P1 de cobertura del frontend: las páginas de 1.000+ líneas que citaba ya no existen.
- **Sigue abierto y requiere acción externa:** el P0 de los backups sin copia remota
  (configuración de infraestructura). El índice del scoring en frío ya existe en
  `v84_lic_universo_cpv_index`; queda medir su efecto tras aplicar la revisión, no
  volver a implementarlo.

---

## P0 — Urgente

### [P0] El feed ATOM de PLACSP está congelado desde el 2026-09-08 y nada lo avisa
- **Área:** scraper/atom_live.py, scheduler/healthcheck.py, .github/workflows/scrape-daily.yml
- **Problema:** medido el 2026-09-24. La cabecera de
  `licitacionesPerfilesContratanteCompleto3.atom` se regeneró el 2026-09-23
  (`Last-Modified`), pero su entrada más reciente es del 2026-09-08 22:31 y las
  páginas `next` siguen hacia atrás desde ahí. El cursor `placsp` está en ese
  mismo instante, así que cada pasada lee una entrada, para con
  `stopped=cursor_reached` e ingiere 0 avisos (run 35978335055) — en verde. El
  healthcheck da PLACSP por «fresca» (`lag_hours: 0.4`) porque mide cuándo acabó
  el último run, no la antigüedad del dato. El ZIP mensual
  `..._202609.zip` sí se regeneró el 2026-09-24 04:01 GMT.
- **Acceptance criteria:**
  - Recuperar el hueco: `scrape-bulk.yml` con `months=1` (acción del usuario:
    escribe en producción) y comprobar que el corpus PLACSP del 09-08 en adelante
    aparece. *Lanzado el 2026-09-25 (run 36127626642); falta comprobar el
    corpus.* `months=1` procesa el mes en curso (`meses_a_procesar`). No cubre
    `placsp_watched_company_awards`, que lee el mismo ATOM y sigue parado.
  - ~~El healthcheck avisa cuando el `last_seen_updated` de una fuente con cursor
    de dato (PLACSP, TED) supera un umbral propio, además de `last_success_at`.~~
    **Hecho el 2026-09-25:** `RegisteredSource.max_antiguedad_dato_hours` (48 h
    PLACSP, 168 h TED) y el estado `sin_datos_nuevos` en
    `comprobar_frescura_fuentes`, con aviso `fuente_sin_datos_nuevos:<fuente>`.
    Mientras el ATOM siga congelado avisará en cada healthcheck: es la señal
    que faltaba, no ruido.
  - Decidir si el carril diario cae al ZIP del mes en curso cuando el ATOM no
    avanza durante N pasadas.
- **Files de partida:** [scraper/atom_live.py](../scraper/atom_live.py), [scheduler/healthcheck.py](../scheduler/healthcheck.py), [scraper/connectors/__init__.py](../scraper/connectors/__init__.py)
- **Riesgo:** bajo para el aviso (solo añade warnings); medio para el fallback al ZIP, que compite por la ventana del carril diario.

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

### [P1] Mercado sin filtros: aplicar `v142` en producción y medir
- **Área:** db/alembic (`v142_lic_indices_analitica`), db/repositories/aggregates.py
- **Problema:** `licitaciones` tiene ~713k filas y ~870 MB de heap (97 % PSCP) en un
  Supabase Micro (`shared_buffers` 256 MB, E/S limitada), y cada `GROUP BY` que la
  recorre tarda de 5 a 15 s según la caché (medido el 2026-09-25: `geography_by_ccaa`
  sin filtros, 15,2 s, 87k páginas leídas de disco). Las vistas de Mercado encadenan de
  2 a 6 recorridos: en los logs de Render, `/analytics/organos` y `/proyectos-modulos`
  dan 500 por `statement_timeout` (30 s por sentencia), `/trends?group_by=month` tarda
  20-72 s, `/trends-cpv` ~40 s y `/geography` ~30 s.
- **Hecho (2026-09-25):**
  - `?tecnologia=` va por índice de tecnología: vistas SAP de 33-41 s a 0,1-2 s (#347).
  - Órganos agrega por hash: el treemap, que era la sentencia que moría (buscaba los 30
    órganos mayores y leía sus filas una a una por `idx_organo`), tarda 4,7 s sin
    filtros; la moda y el recuento de órganos dejan de ordenar la tabla en disco.
  - Migración `v142`: índice cubriente `idx_lic_analitica` para las agregaciones sin
    filtros, `idx_lic_tecnologia_cubriente` para las del ámbito de tecnología y
    autovacuum al 2 %. Con índices hipotéticos (`hypopg`) el planificador ya elige
    Index Only Scan para geografía, tendencias y las tres de órganos.
- **Acceptance criteria:**
  - `migrate.yml` con `mode=apply` (acción con escritura en producción: la lanza el
    usuario) y, después, `indisvalid` de los dos índices, su `pg_relation_size`
    anotado aquí y un `EXPLAIN` de `geography_by_ccaa` sin filtros con Index Only Scan.
  - Cada vista de Mercado sin filtros responde en < 3 s (p95 de `duration_ms` en los
    logs `http_request` de Render) y siete días sin `QueryCanceled` en
    `/api/v1/analytics/*`.
- **Queda fuera:** `/proyectos-modulos` sin filtros sigue leyendo `titulo` (regex de
  módulos SAP) y no cabe en el índice; `/competitive/renovaciones` sin tecnología
  (8-31 s) va por otro SQL. Si el índice no basta: snapshot del ámbito por defecto en
  `kpi_precompute` (ADR-026, camino 3; el cierre ya usa 9-15 de sus 20 minutos) o
  subir el cómputo de Supabase (con 4 GB la tabla cabría en caché).
- **Files de partida:** [db/alembic/versions/v142_lic_indices_analitica.py](../db/alembic/versions/v142_lic_indices_analitica.py), [db/repositories/aggregates.py](../db/repositories/aggregates.py), [tests/test_v142_indices_analitica.py](../tests/test_v142_indices_analitica.py)
- **Riesgo:** medio — los índices son aditivos, pero migran schema: +100-200 MB de disco
  y más escritura por fila; el autovacuum al 2 % añade E/S de fondo.

### [P1] Tras desplegar el dedupe por referencia de TED, re-leer TED y medir cuánto se marcó
- **Área:** scraper/connectors/ted.py, services/dedupe.py (ADR-026, addendum 2026-09-24)
- **Problema:** `detect_duplicados_por_referencia` solo empareja los avisos que el
  conector re-lee (ventana de 14 días): BT-22 y el `idEvl` no son columnas. Lo ya
  ingerido conserva además el título con el prefijo «España – {CPV} – » y la
  etiqueta `DESARROLLO` que ese prefijo le ponía (17 % de una muestra de 300).
- **Acceptance criteria:**
  - `python -m scraper.connectors.ted --desde 20250101` ejecutado en producción
    (acción con escritura: la lanza el usuario o un `workflow_dispatch`).
  - Log `dedupe_referencias_detected` con el recuento, y
    `SELECT COUNT(*) FROM licitaciones_duplicados WHERE clave_match LIKE 'idEvl:%' OR clave_match LIKE 'expediente:%'`
    anotado aquí junto al total de filas `ted`.
  - Ninguna fila `ted` con título que empiece por `España –`.
- **Files de partida:** [scraper/connectors/ted.py](../scraper/connectors/ted.py), [services/dedupe.py](../services/dedupe.py)
- **Riesgo:** bajo — el upsert es idempotente y las marcas `confirmed` automáticas no pisan lo que un humano resolvió.

### [P1] La vista canónica todavía puede preferir TED, y el bulk no cuenta como PLACSP
- **Área:** db/sql_fragments.py (`_criterios_canonicos_sql`), services/dedupe.py (`_rango_canonico`), db/alembic
- **Problema:** el orden de canónica es `fuente <> 'placsp'`, fecha de publicación,
  primera extracción e id. Dos defectos: TED no pierde frente a las demás fuentes
  cuando un par colapsa por clave sin referencia explícita (gana la más antigua),
  y las filas que refrescó el carril bulk llevan `fuente = 'bulk_YYYYMM'` —el
  upsert reescribe `fuente`—, así que pierden la preferencia de PLACSP. El
  dedupe por referencia ya aplica «TED nunca canónica» y cuenta el bulk como
  PLACSP; la vista no.
- **Acceptance criteria:**
  - `_criterios_canonicos_sql` y su gemelo `_rango_canonico` ordenan PLACSP (con
    `bulk_%`) → resto → TED, y `tests/test_dedupe_publico.py` fija la paridad.
  - Migración nueva que reconstruye `licitaciones_canonicas` por permuta, como
    `v102` (requiere OK: AGENTS.md §6), y `tests/test_mv_canonicas_definicion.py`
    apuntando a ella.
  - Delta medido en producción: cuántas canónicas cambian de fila (y de URL).
- **Files de partida:** [db/sql_fragments.py](../db/sql_fragments.py), [db/alembic/versions/v102_mv_canonicas_clave_inmutable.py](../db/alembic/versions/v102_mv_canonicas_clave_inmutable.py), [services/dedupe.py](../services/dedupe.py)
- **Riesgo:** alto — reconstruye la vista de la superficie pública y mueve URLs del sitemap.

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

### [P1] [Ola 1 · S1] Identidad y equipo: invitar sin cuenta previa, OIDC y el ratchet de `user_key`
- **Área:** api/routes/auth.py, services/organizations.py, db/repositories/organizations.py, db/users.py, shared/identity.py, scripts/check_user_key_ratchet.py
- **Problema:** una organización no puede incorporar a nadie que no tenga ya cuenta —`add_member_by_email` rechaza el email aunque `organization_memberships.status` admita `invited` desde `v61`—, el único OAuth es Google (un partner con Microsoft 365 no entra con su identidad), y la identidad interna sigue derivándose del email: `user_key` aparece en 60 ficheros (grep 2026-09-05), así que un cambio de email es un cambio de clave primaria de facto.
- **Decisiones ya tomadas (2026-09-06):** D17 → Entra ID multi-tenant reutilizando `OAUTH_ALLOWED_DOMAINS` y `access_grants`; D18 → ratchet ahora y migración aditiva por olas después (esa segunda fase es T4 del plan, no este ítem).
- **Progreso T4 (2026-09-14, v129 · ADR-030 fase 2):** `user_id` junto a `user_key` en las doce tablas de usuario (nueve nuevas + FK e índice en las tres que ya la tenían), backfill por email en SQL y lectura dual + escritura doble en `db/`, `services/notifications.py`, `services/watchlist_rules.py` y los productores de alertas; GDPR exporta y borra por id o por clave (y cubre por fin `saved_filters`). Test de aceptación del ADR: `tests/test_user_id_cambio_email_integration.py`. **Queda la fase 3** (dejar de escribir `user_key`, recrear las PK de `user_profiles`/`radar_dismissals`, retirar `user_key` del payload de `watchlist_rule.matched` con RFC, y llevar el ratchet a cero).
- **Progreso fase 3 (2026-09-18, v135, rama `worktree-agent-a8484f81d7c8a27e2`):** PK de `user_profiles` → `(user_id)` y de `radar_dismissals` → `(user_id, id_externo)`, con backfill y fallo ruidoso si queda alguna fila sin id o duplicada; `user_profiles` ya no escribe `user_key`; `log_event(actor=…)` saca seis ficheros del ratchet (69 → 63); RFC `draft` [2026-09-18](rfc/2026-09-18-rfc-retirar-user-key-payload-watchlist-rule-matched.md) para el payload del webhook, con el campo intacto hasta la ventana y la sustitución pendiente de decisión humana. **Queda:** `user_notifications`/`follows`/`watchlist_*` siguen tecleadas por `user_key` (y con ellas `radar_dismissals` la sigue escribiendo); aplicar v135 en producción (antes del deploy del código) y regenerar `docs/database-schema.md`. *Estado (2026-09-19):* `docs/database-schema.md` ya está regenerado con v135 y v140 (`98f34bee`; su cabecera dice `v138_notice_type_code`).
- **Acceptance criteria:** los de S1.1–S1.4 del plan v2, sin redefinirlos aquí. Los cuatro subítems son independientes y se pueden entregar por separado; S1.3 (dominio propio) es acción humana.
- **Files de partida:** [docs/plans/2026-09-plan-arquitectura-v2.md](plans/2026-09-plan-arquitectura-v2.md) (§5, S1), [services/organizations.py](../services/organizations.py), [api/routes/auth.py](../api/routes/auth.py)
- **Riesgo:** medio — S1.2 toca el login, que es el camino por el que entra todo el mundo; el resto es aditivo.

### [P1] [Ola 1 · S2] La organización no sabe quién es: NIF, capacidad y go/no-go asistido
- **Área:** services/go_no_go.py, db/repositories/organization_capabilities.py, services/pursuit_awards.py, services/analytics/affinity.py, web/src/app/(dashboard)/equipo
- **Problema:** `OrganizationSettings` solo guarda `tecnologias`. Sin NIF, `PursuitAdjudicacionDetectada` tiene que pedir confirmación humana para cerrar una oportunidad —lo dice su propio docstring: «el sistema no conoce el NIF de la organización»— y «contra quién» no puede excluir a la propia organización de la lista de competidores. Sin perfil de capacidad, la ficha del pliego (certificaciones, solvencias, equipo) no tiene contra qué contrastarse: el producto extrae el requisito y deja al usuario comprobándolo a mano.
- **Decisión ya tomada (2026-09-06):** D11 → tablas propias (`organization_nifs`, `organization_capabilities`), no un JSON en `settings_json`, porque el cierre por NIF y el contraste de solvencia se resuelven en SQL.
- **Acceptance criteria:** los de S2.1–S2.4 del plan v2. El veredicto del checklist nunca decide por el usuario: `cumple | no_cumple | desconocido`, ningún `cumple` sin `EvidenceRef`, y `desconocido` cuando falta el dato — es la misma regla de ADR-014 aplicada a una decisión en vez de a una cifra.
- **Estado:** lo dice el §5 del plan, no este ítem — ver la nota de cabecera. Dos precisiones sobre el **Problema** de arriba, que ya no describe el código: el docstring que citaba («el sistema no conoce el NIF de la organización») se corrigió el 2026-09-08 porque el código lo desmentía, y la exclusión de la propia organización de «contra quién» ya está viva. Lo que S2 tuvo que arreglar en esa tanda no fue escribir el motor —estaba escrito desde #274— sino enchufarlo: cuatro piezas probadas y sin ningún llamador de producción.
- **Files de partida:** [docs/plans/2026-09-plan-arquitectura-v2.md](plans/2026-09-plan-arquitectura-v2.md) (§5, S2), [shared/dto.py](../shared/dto.py)
- **Riesgo:** medio — dos migraciones y una regla de producto nueva; el golden `golden_go_no_go.jsonl` es la red.

### [P1] [Ola 1 · S5] Cola de trabajo y worker: un despliegue mata lo que un usuario pidió
- **Área:** shared/jobs.py, db/repositories/jobs.py, scheduler/worker.py, api/routes/jobs.py, scheduler/pipeline_runs.py, render.yaml
- **Problema:** la extracción asíncrona de la ficha corre en `BackgroundTasks` de la API con 30 s de drenado al apagar (`api/app.py`), y `autoDeploy` está activo en el servicio real: un push a `master` en mitad de una extracción la pierde, y el usuario ve un estado que nunca avanza. El cierre post-ingesta son quince pasos secuenciales dentro de un job de Actions cada cuatro horas, donde un paso caído arrastra a los que no dependen de él.
- **Decisión ya tomada (2026-09-06):** D14 → worker en Render para lo que pide un usuario y Actions para lo programado, sobre la misma tabla de cola. El servicio nuevo exige O0.2 cerrado primero (un solo camino de despliegue).
- **Acceptance criteria:** los de S5.1–S5.4 del plan v2, incluidos los dos que son medibles sin producción: dos consumidores concurrentes procesan cien jobs exactamente una vez, y `grep -rc "BackgroundTasks" api/routes/licitaciones/` = 0 (el fichero es un paquete desde 2026-09).
- **Files de partida:** [docs/plans/2026-09-plan-arquitectura-v2.md](plans/2026-09-plan-arquitectura-v2.md) (§5, S5), [scheduler/pipeline_runs.py](../scheduler/pipeline_runs.py), [api/app.py](../api/app.py)
- **Riesgo:** medio — servicio nuevo en producción y cambio del camino por el que se sirve la ficha.

---

### [P1] El despachador del outbox no lo invoca ningún plano
- **Área:** scheduler/jobs/event_dispatch.py, scheduler/pipeline_runs.py, scheduler/jobs/__init__.py
- **Problema:** `scheduler/jobs/event_dispatch.run()` está escrito y probado (S4.1), pero ni el cierre de `pipeline_runs.py` ni el registro de jobs de APScheduler lo llaman (comprobado el 2026-09-18 buscando `event_dispatch` fuera de `tests/` y `docs/`). Ningún evento de `domain_events` se entrega: ni notificaciones in-app, ni correos de `pursuit.*`, ni webhooks del catálogo, ni los nuevos `pursuit.task_due`/`pursuit.mentioned`. La alerta `DomainEventsBacklogHigh` acabará disparándose por esto.
- **Por qué no se hizo en el mismo cambio:** cablearlo vacía de golpe la cola acumulada desde que existe el outbox —correos y webhooks incluidos, con fechas viejas—. Hace falta decidir antes si se marca como despachado lo anterior a una fecha o se entrega.
- **Acceptance criteria:** un paso del cierre (plano `pipeline`, ADR-012) llama a `event_dispatch.run()`; decisión documentada sobre la cola histórica; `domain_events_pending` baja en producción.
- **Riesgo:** medio — primera vez que salen correos y webhooks del outbox.

## P2 — Media

### [P2] Decidir si el listado `/licitaciones` esconde duplicados (ADR-026 D23 dice que sí)
- **Área:** db/repositories/licitaciones.py (`_base_filters`), db/repositories/aggregates.py
- **Problema:** D23 fija «Radar, listados: esconde `pending` y `confirmed`», pero
  `_base_filters` —listado, cursor y export— no excluye ningún duplicado, y el
  guardrail de dedupe lo exime como «CRUD por diseño». El Radar sí los esconde.
  Con las marcas de TED de 2026-09-24, el Radar deja de enseñar la copia TED y el
  listado la sigue enseñando.
- **Acceptance criteria:**
  - Decisión escrita (en ADR-026 o en el guardrail) sobre cuál de las dos reglas manda.
  - Si se esconden: `exclude_duplicados_presentacion_sql` en `_base_filters` y en
    la rama FTS, y los contadores de `/resumen` que abren el listado miden lo mismo
    (hoy los fija un test de paridad).
- **Files de partida:** [db/repositories/licitaciones.py](../db/repositories/licitaciones.py), [tests/test_dedup_guardrail.py](../tests/test_dedup_guardrail.py)
- **Riesgo:** medio — cambia el universo del listado, el cursor y el export a la vez.

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

### [P2] `render.yaml` no gobierna el servicio que corre en producción
- **Área:** render.yaml, Render Dashboard (acción del usuario)
- **Problema:** el Blueprint está en el repo, pero el servicio de producción se creó a mano por el dashboard y nunca se vinculó a él, así que el fichero documenta una intención que nadie aplica: editarlo no cambia nada y leerlo puede inducir a error sobre cómo está configurado el servicio real. Lo que sí está activo es `autoDeploy`, y **sin healthcheck configurado** — es decir, un deploy que arranca mal reemplaza igualmente al que funcionaba, sin rollback automático. (Estado observado en la sesión del 2026-08-04; **reconfirmar en el dashboard antes de actuar**, que es barato.)
- **Progreso 2026-09-06 (O0.2 del plan v2, cierra D4):** la decisión ya está tomada y escrita — **se vincula el Blueprint y manda `render.yaml`**, con `autoDeploy: false` y `deploy.yml` como único disparador, porque es la única de las dos ramas que conserva CI como gate en vez de dejarlo en advisory. Lo que queda de este ítem es **exactamente lo que un agente no puede hacer**: vincular el Blueprint y apagar `autoDeploy` en el dashboard, y comprobar que un push a `master` produce un solo deploy.
- **Acceptance criteria (lo que queda, todo acción del usuario):**
  - Blueprint vinculado y `autoDeploy` apagado en el servicio real; la cabecera de `render.yaml` anota la fecha de verificación.
  - `healthCheckPath` efectivo, verificado con un deploy deliberadamente fallido.
  - Un push a `master` produce exactamente un deploy, observado siete días.
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
- **Progreso (2026-09-18, PARCIAL, rama `worktree-agent-ae7fea40cc310a705`):** unificado con T2 del plan de arquitectura v2. El plan de columna sombra está escrito con el nombre que fijó el plan, **`importe_num numeric(14,2)`** (no `importe_f8`: céntimos exactos en vez de otro float), más `duracion_valor_num numeric` (`v133_nucleo_tipado_sombra`, sólo catálogo, sin reescritura), escritura dual en `db/upsert.py` que traduce el `float` del conector **antes** de que pase por `real`, backfill por lotes (`scripts/backfill_nucleo_tipado.py`) y runbook de la ventana ([runbooks/nucleo-tipado-ventana.md](runbooks/nucleo-tipado-ventana.md)). `FLOAT_REL_TOL` **no se ha tocado**. Pendiente, todo en producción: aplicar la ventana, verificar cero divergencias, mover las lecturas de `importe` a la sombra, y sólo entonces bajar la tolerancia y limpiar `licitaciones_history`/`contrato_eventos`. El test de round-trip exacto contra Postgres (`tests/test_nucleo_tipado_pg.py`) está escrito y **no se ha ejecutado**.

### [P2] Filas nuevas con importe y sin `importe_tipo`: la auditoría lo viola a diario y crece
- **Área:** scraper/connectors/, db/upsert.py, scripts/audit_domain_truth.py
- **Problema:** el umbral `importe/filas_nuevas_sin_tipo` (cero, sin margen, desde `v113`) se supera en las siete ejecuciones archivadas de `domain-truth.yml` del 12 al 18/09, y la cuenta **crece cada día**: 131, 131, 152, 190, 238, 279, 316 filas con importe desde el 2026-09-06 y sin base declarada. Algún camino de escritura no puebla `importe_tipo`; el correo de alerta lleva una semana diciendo lo mismo. (En la misma serie, `ml_proba` > 0,7 está en el 72,9 % de lo puntuado frente al 50 % del criterio: eso es el P2 del corpus de PSCP, ya abierto.)
- **Acceptance criteria:** identificado el camino (por `fuente` de esas filas) y corregido en origen; la cuenta deja de crecer en `domain-truth.json`. El umbral no se relaja.
- **Files de partida:** [db/domain_truth_audit.py](../db/domain_truth_audit.py) (`importe_sin_base_declarada`), [scripts/audit_domain_truth.py](../scripts/audit_domain_truth.py)
- **Riesgo:** bajo — corrección de ingesta; la serie está en el docstring del script.

### [P2] Modelo de baja por lote
- **Área:** services/ml, db/alembic, api/routes/predicciones.py, web/
- **Problema:** el modelo predice la baja **agregada por expediente** porque es la granularidad que puede servir `predicciones_baja` (PK `licitacion_id`) y la que mide `services/ml/calibration.py`. Pero el lote es la unidad sobre la que realmente se puja: en un expediente de 30 lotes, una sola cifra agregada es menos accionable que 30.
- **Acceptance criteria:**
  - Migración de `predicciones_baja` a PK `(licitacion_id, lote_id)` con `lote_id` nullable para expedientes de lote único.
  - `db/repositories/ml_dataset.py` expone la variante por lote (el denominador por fila ya existe: `EFFECTIVE_BUDGET_SQL`), `calibration.py` compara a la misma granularidad, y el DTO/endpoint/frontend exponen el desglose.
  - Se compara `mae_p50` por lote contra el agregado actual antes de sustituirlo; si no mejora, se documenta y se queda el agregado.
- **Files de partida:** [db/repositories/ml_dataset.py](../db/repositories/ml_dataset.py), [services/ml/calibration.py](../services/ml/calibration.py), [api/routes/predicciones.py](../api/routes/predicciones.py)
- **Progreso (2026-09-18, rama `worktree-agent-a0a81e5a659bd1de7`) — parte de código hecha, falta la medida:** `v140_predicciones_baja_por_lote` retira la PK y deja dos únicos parciales (patrón v65/v110): uno por expediente (`lote_numero IS NULL`) y otro por `(licitacion_id, lote_numero)`. La identidad del lote es **`lote_numero`, no `lote_id`**: `replace_lotes` renumera `lotes.id` en cada re-ingesta y la FK CASCADE de v86 habría borrado la predicción justo en la re-ingesta que trae la adjudicación, así que la calibración por lote no habría visto nunca un par (la columna `lote_id`, siempre NULL, se elimina). Hay dataset y features por lote (`construir_dataset_baja(por_lote=True)`, importe del lote), modelo propio `baja_model_lote` (`score_predicciones.py --model baja --por-lote --train`), batch por lote tras `ML_BAJA_POR_LOTE` (apagado por defecto), lecturas agregadas filtradas por `lote_numero IS NULL`, desglose aditivo `lotes` en `GET /licitaciones/{id}/prediccion-baja` y en el bloque de baja del detalle. **Pendiente, humano y con BD real:** correr `ENV=dev python scripts/comparar_baja_por_lote.py` (backtest sobre los mismos lotes + la comparación servida) y decidir si se enciende `ML_BAJA_POR_LOTE`; hasta entonces el agregado es lo servido. De paso: `PrediccionBajaResult.model_version` (contrato `string`) daba 500 con un modelo activo (int); se convierte en el validador sin cambiar el contrato.
- **Riesgo:** medio — migración de una tabla materializada + cambio de contrato API.

### [P2] Sustituir los fixtures sintéticos del corpus CODICE por expedientes reales
- **Área:** tests/fixtures/placsp/
- **Problema:** los once casos del corpus golden son estructuralmente fieles al CODICE pero escritos a mano: la sesión que los creó no tenía ZIP mensuales cacheados ni acceso al feed. El valor del corpus está en codificar variabilidad que nadie imaginó, y eso solo lo dan los datos reales.
- **Acceptance criteria:**
  - `ENV=dev python scripts/capture_placsp_fixtures.py --caso <caso>` sustituye cada fixture sintético por uno real, y `python -m tests.test_codice_parser_golden --update` regenera el golden con el diff revisado.
- **Files de partida:** [scripts/capture_placsp_fixtures.py](../scripts/capture_placsp_fixtures.py), [tests/fixtures/placsp/README.md](../tests/fixtures/placsp/README.md)
- **Riesgo:** bajo — solo tests.


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
- **Progreso parcial (2026-09-14, Ola 1 · Taxonomía):** parte del 0,46 % era vocabulario, no población: el diccionario solo tenía castellano y la PSCP publica en catalán. `config/keywords.py` añade nueve categorías de TI con formas en catalán, euskera y gallego ([docs/taxonomia-tecnologica.md](taxonomia-tecnologica.md)); tras resembrar, la tasa de positivos de PSCP hay que volver a medirla antes de decidir la bifurcación. No toca la población de entrenamiento ni `validate_training_data`.
- *Estado (2026-09-19):* **la bifurcación ya se tomó en código, por la opción 1**, y el ítem no lo decía. Desde S6.1 del plan v2 (`#274`, 2026-09-08) `train_from_db` (`scraper/ml_training.py:374-418`) no lee `licitaciones` entera: entrena sobre `db.repositories.ml_dataset.filas_entrenamiento_sap`, acotada por `poblacion_clasificador_sql` (universo tecnológico observado, no un filtro por nombre de fuente, y sin duplicados confirmados), pasa `validate_training_data` en ese mismo camino y registra la población como `train_population`. Lo que sigue abierto es la consecuencia que la propia opción 1 anunciaba —el modelo puntúa una población distinta de la que aprende— y la medida: `domain-truth.yml` seguía dando `ml_proba > 0,7` en el 72,9 % de lo puntuado del 12 al 18/09 (ver el P2 de `importe_tipo`). No se comprobó aquí si hay ya una versión de `sap_classifier` entrenada con esa población.

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
- **Progreso parcial (2026-09-18, rama worktree-agent-a3fd0bc81b8a949c2) — los dos primeros criterios ya estaban en código; queda solo la decisión humana.** Comprobado contra el código: el criterio escrito existe desde #274 (v2 S6.4) — `services.ml.promotion.evaluar_promocion_predictiva`: una versión solo es promocionable si su mejora sobre el baseline mide al menos `MIN_IMPROVEMENT_OVER_FOLD_DISPERSION` (1.0) veces la dispersión de la métrica entre folds, sin dispersión medida no se promociona, y los criterios del RFC entran como motivos extra. `baja_model.entrenar` y `retencion_model.entrenar` lo aplican y dejan el veredicto en `notes` (`promotion_reason`); retención registra `pr_auc_baseline` (prevalencia) y `pr_auc_std_folds` (bloques contiguos de validación). Tests en `tests/test_ml_promocion_predictiva.py`; el runbook `model-rollback.md` lo cita. Esta rama añade a retención el rival de antigüedad que pedía el criterio: `pr_auc_baseline_antiguedad` (ordenar por `antiguedad_relacion_meses`), **informativo, no gatea**. Aplicado a los números de arriba, baja v2 sale «indistinguible de ruido» (0.005 < 0.0129). **Falta (humano):** relanzar `train-predictivos.yml` para que retención tenga dispersión y rival registrados —v1 es anterior al gate—, y decidir activar o descartar con el `promotion_reason` delante.
- **Progreso (2026-09-24, rama `claude/ml-scoring-improvements-da84e5`) — activar ya no rompe el scoring al mes siguiente.** Hasta hoy todas las versiones se publicaban como `baja_model.pkl`/`retencion_model.pkl` con `--clobber`: activar vN y dejar que el reentrenamiento mensual registrara vN+1 sin activar pisaba el asset de vN, y `ml-scoring.yml` caía cada día por `ModelArtifactMismatch` hasta activar vN+1. Ahora cada versión nueva lleva un nombre derivado de su contenido (`baja_model-<sha12>.pkl`) en la Release fija `ml-models`. La resolución busca por nombre en `ml-models` → *latest* → las 30 Releases más recientes, así que las filas actuales (v2 y v1, de nombre fijo) se siguen encontrando. La decisión pendiente es solo la de arriba.

### [P2] ml-scoring: verificar en producción el arreglo del 2026-09-24 y cerrar sus flecos
- **Área:** services/ml/, scheduler/jobs/ml_predicciones.py, .github/workflows/ml-scoring.yml, shared/release_assets.py
- **Problema:** El job estaba al borde de su `timeout-minutes: 20`: el 2026-09-20 consumió 1.190 de los 1.200 s. Unos 11 minutos se iban en features de retención que la rama baseline calculaba y tiraba, y otro minuto en hilos del pool que no se cerraban. La rama `claude/ml-scoring-improvements-da84e5` corrige eso y nueve puntos más:
  - disparo tras la ingesta, con un guard de una corrida al día;
  - preflight de schema;
  - verify por `computed_at`;
  - artefactos con nombre por contenido;
  - drift que solo alerta según el régimen servido;
  - dedup de alertas;
  - población sin zombis;
  - baseline de retención con shrinkage jerárquico;
  - purga de filas viejas.

  Falta medirlo en producción y cerrar lo que no entró.
- **Acceptance criteria:**
  - En los primeros runs tras el merge:
    - el step de scoring tarda menos de 6 min (`duraciones_s` en el resumen del job);
    - hay una sola corrida por día UTC (las demás salen con `ya_puntuado_hoy`);
    - el preflight sale verde;
    - el verify corre en modo `corrida`.
  - Medir cuántas filas borra `purgar_sin_adjudicar` en su primera pasada y cómo cambia el PSI del drift con la población viva. Antes, la mediana de `n_obs_organo` era 3 en scoring y 1.293 en la referencia.
  - Decidir `ML_RETENCION_EXCLUIR_RESUELTOS` tras auditar una muestra de `resueltos_detectados`. Hoy está apagado: la heurística órgano + CPV-4 da falsos positivos en segmentos con mucha actividad, y excluir un contrato lo esconde del orden «score». `scripts/audit_retencion.py` solo audita pares de entrenamiento; hay que añadirle un modo `--resueltos`.
  - Que el entrenamiento de retención deje de ser cuadrático. `construir_pares` llama a `_features_historicas` por cada par (~5,5K pares × ~698K adjudicaciones × 2), y `_emparejar` es O(Σ n²) por segmento. Solución: índices por clave más bisect, con paridad contra la referencia como en `tests/test_ml_retencion_serving.py`.
  - Resolver la clave de `predicciones_retencion` **antes de activar `retencion_model`**; exige migración. La tabla guarda un riesgo por expediente (`licitacion_id` es la PK), pero Renovaciones pinta una fila por empresa adjudicataria. Con el modelo, que sí depende de la empresa, un expediente con varios adjudicatarios mostraría a todos el riesgo del primero.
  - Pasar a `locate_release_asset` y a una Release fija lo que aún publica y busca solo en *latest*: `ensure_downloaded` de `scraper/ml_classifier.py` y de `scraper/tech_classifier.py`, más `train-model.yml` y `train-tech.yml`.
  - Arreglar `observability/logging.py::redact_dsn`, que no redacta la contraseña de los DSN con driver (`postgresql+psycopg://…`). Hoy `db/schema_revision.py` lo cubre con su propia regex.
- **Files de partida:** [scheduler/jobs/ml_predicciones.py](../scheduler/jobs/ml_predicciones.py), [services/ml/retencion_labels.py](../services/ml/retencion_labels.py), [shared/release_assets.py](../shared/release_assets.py), [.github/workflows/ml-scoring.yml](../.github/workflows/ml-scoring.yml)
- **Riesgo:** bajo para las verificaciones; medio para la clave de `predicciones_retencion`, que exige migración.

### [P3] Las 47 adjudicaciones con fecha imposible siguen anclando filas de entrenamiento
- **Área:** services/ml/features.py, db/repositories/ml_dataset.py, scraper/connectors/pscp.py
- **Problema:** el #262 filtra en `_fecha_opt` los años de menos de cuatro cifras (`0019-12-10` del expediente `19/002/5-2`, `0202-02-27` de PSCP), que es lo que rompía el round-trip de `%Y`. Pero de las **47 filas** de `adjudicaciones` con `fecha_adjudicacion` imposible —medidas contra producción el 2026-09-03— la mayoría son `1899-12-30`: el cero de la epoch de Excel, o sea como PSCP exporta una celda vacía. Esas pasan el filtro, porque tienen cuatro cifras y parsean bien. Y el ancla del dataset es `LEAST(fecha_publicacion, fecha_adjudicacion)`, así que ganan: la fila entra en el train de **todos** los folds con los acumuladores históricos vacíos, y su adjudicación los alimenta como si precediera a todo el histórico.
- **Por qué no se subió el umbral con el #262:** el `_ANIO_MINIMO = 1000` está justificado por la asimetría de `%Y` entre `strptime` y `strftime`, que es un hecho del parser y no admite discusión. Un umbral de *plausibilidad* (1990, 2008…) es una afirmación distinta —sobre los datos, no sobre el formato— y merece decidirse aparte en vez de colarse dentro de una constante que hoy significa otra cosa.
- **Acceptance criteria:**
  - Decidido dónde se corta: el conector de PSCP (que es quien genera el `1899-12-30`), el parser, o el SQL del dataset.
  - Las 47 filas dejan de anclar filas de entrenamiento, verificado con la misma query que las midió.
- **Files de partida:** [services/ml/features.py](../services/ml/features.py) (`_fecha_opt`), [db/repositories/ml_dataset.py](../db/repositories/ml_dataset.py) (`fecha_anchor`), [scraper/connectors/pscp.py](../scraper/connectors/pscp.py)
- **Riesgo:** bajo — son 47 filas de ~691k adjudicaciones; el impacto es de calidad de dataset, no de disponibilidad.
- **Progreso parcial (2026-09-18, rama worktree-agent-a3fd0bc81b8a949c2) — decidido: se corta en los dos extremos, y en ninguno con `_ANIO_MINIMO`.** El conector de PSCP ya descartaba en origen desde C4.4 las fechas anteriores a `shared.dates.ANIO_MINIMO_PLAUSIBLE` (1990; cubre `1899-12-30` y `1900-01-00`), pero no puede ver las filas ya escritas. Para esas, `db/repositories/ml_dataset.py` añade `fecha_adjudicacion >= '1990-01-01'` (como parámetro, `_filtro_fecha_adj`) en las dos CTE de `_sql_agregado` y de `_sql_por_lote` y en `adjudicaciones_por_empresa` (HHI): la fila se trata como adjudicación sin fecha —lo que es—, que ya quedaba fuera por el `IS NOT NULL`. `_ANIO_MINIMO = 1000` del parser no cambia de significado (lo fija un test). Efecto colateral buscado: las subconsultas de lotes dejan de contar adjudicaciones sin fecha que la CTE principal nunca vio. Tests: `tests/test_ml_dataset_fecha_plausible.py` (SQL y parámetros sin BD; uno contra Postgres **no ejecutado** en local) y el de año corto de `tests/test_ml_features.py` adaptado. **Falta:** verificar contra producción, con la query de `db.domain_truth_audit.adjudicaciones_con_fecha_imposible`, que ninguna de esas filas aparece en `pares_baja_agregada()` — sin acceso a la BD desde esta rama.

### [P2] [Ola 1 · S3] Oportunidad por lote, y saber si el Radar prioriza bien
- **Área:** db/repositories/pursuits.py, services/pursuits.py, services/product_metrics.py, web/src/app/(dashboard)/oportunidades
- **Problema:** `pursuits` es única por `(organization_id, licitacion_id)`, así que no se puede abrir una oportunidad por lote — que es la unidad sobre la que de verdad se puja, y que los lotes existen desde `v65`. Y el bucle del Radar no se cierra: `score_al_abrir` y `banda_al_abrir` se persisten desde `v93` y **ningún módulo de producción los lee**, o sea que el producto no puede responder si la banda «Caliente» acierta.
- **Decisión ya tomada (2026-09-06):** D12 → `pursuits.lote_id` nullable con dos únicos parciales (patrón `v65`); `NULL` significa expediente completo y las filas existentes no cambian.
- **Acceptance criteria:** los de S3.1–S3.3 del plan v2. La precisión por banda solo se pinta con N ≥ 10 y, por debajo, dice «sin datos suficientes» (ADR-014); la propuesta de pesos nunca se aplica sola.
- **Files de partida:** [docs/plans/2026-09-plan-arquitectura-v2.md](plans/2026-09-plan-arquitectura-v2.md) (§5, S3), [db/repositories/pursuits.py](../db/repositories/pursuits.py)
- **Relación:** desbloquea el P2 «Modelo de baja por lote» de este backlog (S6.5 del plan sirve las filas por lote que `predicciones_baja` ya guarda desde `v86`).
- **Estado:** lo dice el §5 del plan, no este ítem. **Corrección de un hecho de la línea anterior**, comprobada el 2026-09-08: `predicciones_baja` **no guarda filas por lote**. `v86` dejó la columna `lote_id` preparada, pero el único escritor (`score_predicciones_baja`) nunca la rellena y su `ON CONFLICT(licitacion_id)` ni siquiera dejaría convivir dos filas del mismo expediente. S6.5 sirve la estimación agregada declarándolo en `prediccion_ambito`; la `baja_real` sí es del lote. El «Modelo de baja por lote» sigue, pues, siendo trabajo de ML, no de fontanería. (2026-09-18: `v140` ya permite y escribe filas por lote, identificadas por `lote_numero`; ver el progreso de ese ítem.)
- **Riesgo:** medio — cambia la clave única de una tabla viva; `plan` antes de `apply`.

### [P2] [Ola 1 · S4] Eventos y salida: siete almacenes con forma de evento y ningún backbone
- **Área:** db/events.py, shared/events.py, scheduler/jobs/event_dispatch.py, api/routes/webhooks.py, services/notifications.py, api/routes/watchlist_rules.py
- **Problema:** conviven `pursuit_events`, `contrato_eventos`, `licitaciones_history`, `user_notifications`, `pending_digests`, `webhook_deliveries` y `domain_events`, y la tabla de event sourcing solo la escriben dos sitios. El equipo se entera por email o abriendo la consola: los webhooks exigen `require_admin` en todas sus rutas y `_VALID_EVENTS` tiene cuatro tipos. Y un cambio en un expediente seguido —`licitaciones_history` guarda `changed_fields`— no genera ninguna alerta.
- **Decisión ya tomada (2026-09-06):** D13 → plantillas de payload (`json`, `slack_blocks`, `teams_adaptive_card`) sobre el webhook genérico, no integraciones nativas con OAuth de cada plataforma, y webhooks que pueda crear un miembro dentro de su organización.
- **Acceptance criteria:** los de S4.1–S4.6 del plan v2. El que sostiene lo demás es el ratchet de productores: toda inserción directa en `user_notifications`/`pending_digests` fuera del despachador entra en una lista que solo puede encoger.
- **Files de partida:** [docs/plans/2026-09-plan-arquitectura-v2.md](plans/2026-09-plan-arquitectura-v2.md) (§5, S4), [db/events.py](../db/events.py), [api/routes/webhooks.py](../api/routes/webhooks.py)
- **Riesgo:** medio — toca el camino de escritura de pursuits y de reglas.

### [P2] [Ola 1 · S7] Frontend: las tres deudas que dejó a medias el plan de septiembre, más formularios, flags e inspectores
- **Área:** web/src/app, web/eslint.config.mjs
- **Problema:** S5.1 (prefetch en servidor con hidratación), S5.2 (partir las páginas monolito) y S5.9 (grupo de rutas `(privado)`) quedaron sin entregar cuando tres agentes murieron por límite de sesión, y dos de ellas se revirtieron a conciencia (§8 del plan anterior). A eso sumaba el §1 del plan v2, medido el 2026-09-05: doce ficheros de `web/src/app` por encima de 300 líneas, ninguna librería de formularios en las seis pantallas con validación, feature flags que se administran en `/ops` y **ninguna vista lee**, e inspectores de Radar y Detalle que solo existen desde `xl`.
- **Acceptance criteria:** los de S7.1–S7.4 del plan v2, y los de S5.1/S5.2/S5.9 del plan de septiembre tal cual para el primero. La allowlist inicial de `max-lines` son esos doce ficheros y solo puede encoger.
- **Estado:** lo dice el §5 del plan cuando el stream se cierra, no este ítem — ver la nota de cabecera. S7 se está entregando en esta misma ola.
- **Files de partida:** [docs/plans/2026-09-plan-arquitectura-v2.md](plans/2026-09-plan-arquitectura-v2.md) (§5, S7 y la tabla de los doce ficheros en §1)
- **Relación:** S7.1 es la vía por la que avanza el P1 de cobertura de las páginas del frontend: la lógica sale a `_hooks/` testeables en vez de testear el árbol entero.
- **Riesgo:** medio en S7.1 (routing y datos iniciales), como ya dijo el plan anterior.

### [P2] [Ola 1 · S8] Documentos: solo se leen PDF con texto y texto plano
- **Área:** scraper/document_fetcher.py, shared/object_store.py, .github/workflows/pliegos.yml, shared/model_artifacts.py
- **Problema (diagnóstico del §1 del plan v2, medido el 2026-09-05):** `_SUPPORTED_CONTENT_TYPES` admitía dos content-types, así que un pliego en DOCX, ODT o dentro de un ZIP no se procesaba y un PDF escaneado terminaba en error por no haber OCR; y el binario se descartaba tras extraer, de modo que reprocesar exigía volver a PLACSP, cuyas URIs llevan un token que caduca. Es el techo real de la ficha del pliego: lo que no se puede leer no existe para el producto.
- **Acceptance criteria:** los de S8.1–S8.4 del plan v2, sin redefinirlos aquí. Los cuatro son independientes y se entregan por separado; S8.1 y S8.2 llevan migración y dependencias nuevas, ambas pre-autorizadas por D20.
- **Estado:** lo dice el §5 del plan cuando el stream se cierra, no este ítem — ver la nota de cabecera. S8 se está entregando en esta misma ola.
- **Files de partida:** [docs/plans/2026-09-plan-arquitectura-v2.md](plans/2026-09-plan-arquitectura-v2.md) (§5, S8), [scraper/document_fetcher.py](../scraper/document_fetcher.py)
- **Relación:** S8.4 roza el P3 «Un solo transporte para bajar assets de la Release» (cerrado el 2026-09-18): los dos tocan cómo se resuelve un artefacto de modelo, y conviene decidirlos juntos.
- **Riesgo:** medio — el coste del OCR por página se mide en el primer run nocturno y lo acota el tope de páginas.

---

## P3 — Nice to have

### [P3] Descartar los avisos fantasma de Dependabot (manifest `uv.lock` inexistente)
- **Área:** GitHub Security (acción del usuario), .github/dependabot.yml
- **Problema:** 37 de los 38 avisos abiertos apuntan a un `uv.lock` que se borró de `master` en `cc096fb` (2026-05-31). El grafo de dependencias de GitHub conservó una instantánea de ese fichero y **sigue emitiendo avisos nuevos contra ella** — los abiertos van del 2026-07-13 al 2026-08-07, todos posteriores al borrado. La prueba está en el SBOM, que lista a la vez los pines vivos y sus fantasmas (`pillow@12.3.0` ×2 junto a `pillow@12.2.0`; `cryptography@50.0.0` ×2 junto a `46.0.7`), y en el trío del 2026-08-03 sobre `GHSA-g6cj-pr64-35w5`: #82 y #83 (manifiestos vivos) se cerraron el mismo día; #87 (`uv.lock`) sigue abierto y no puede cerrarse nunca.
- **Cómo triar (corregido 2026-08-30):** **no** basta con filtrar por `manifest_path`, y sobre todo no debe convertirse en una regla de auto-descarte. GitHub atribuye mal ese campo: los tres avisos de `cryptography` (#87–#89) salen etiquetados como `uv.lock` pese a que ese paquete **nunca** estuvo en ese fichero. Una regla que descarte por `manifest_path: uv.lock` acabaría tapando en silencio un aviso real de `requirements.txt`. El criterio que sí decide es el pin vivo: comparar `first_patched_version` contra `requirements.txt` / `requirements-dev.txt` / `web/package-lock.json`, aviso por aviso.
- **Acceptance criteria:** los 37 descartados con motivo (`not_used` los 18 de GitPython, que no está en ningún manifiesto; `inaccurate` el resto, cuyo pin vivo ya está parcheado); el listado refleja solo manifiestos reales. La cura de fondo —que el grafo deje de ver `uv.lock`— exige forzar un re-parse del path o abrir ticket a GitHub Support; el toggle del dependency graph no existe en repos públicos.
- **Progreso (2026-09-24):** el 2026-08-30 se descartaron 33 con el criterio de arriba (17 `inaccurate`, 16 `not_used`). El fantasma **sigue emitiendo**: desde entonces han llegado 8 más, todos contra `uv.lock` y ninguno con pin vivo vulnerable — #113 y #114 (`anyio` < 4.14.2: los cuatro `requirements*.txt` fijan 4.14.2), #108–#112 (`GitPython` ≤ 3.1.58: no está en ningún manifiesto) y #105 (`transformers` < 5.10.0: sin pin, entra por los extras `ml`/`ml-embeddings`; la última ejecución de `pliegos.yml` resolvió 5.17.0 y el código no llama a `save_pretrained`). Descartar a mano es un goteo sin fin: el ítem no se cierra hasta aplicar la cura de fondo.
- **Files de partida:** [.github/dependabot.yml](../.github/dependabot.yml)
- **Riesgo:** bajo — no toca código; el cuidado está en verificar cada aviso contra el pin vivo en vez de contra el nombre del manifiesto.

### [P3] Decidir el destino del peso de `graphify-out/` (28 MB y creciendo)
- **Área:** graphify-out, .claude/hooks
- **Problema:** los artefactos commiteados del knowledge graph pesan **28 MB** (medido 2026-08-18): cada clone y cada sesión remota los paga, y el hook de stale-flag deja el working tree dirty en sesiones sin el CLI (que no pueden limpiarlo). El valor para agentes sin CLI es real (AGENTS.md §1), así que es un trade-off consciente a revisar, no un error. **La cifra de este ítem estaba desactualizada: decía 17 MB, o sea que el artefacto creció un 65% mientras la decisión seguía aplazada.** La comparación "~52% del repo" ya no es evaluable tal cual y se retira; lo que decide es el absoluto y su tendencia.
- **Acceptance criteria:**
  - Decisión registrada: mantener como está, excluir `wiki/` (la parte más pesada y más regenerable), o mover a artefacto de CI/LFS con fallback textual documentado en AGENTS.md §1.
- **Files de partida:** [AGENTS.md](../AGENTS.md), [.claude/hooks/](../.claude/hooks/)
- **Riesgo:** bajo — decisión de mantenedor; sin impacto en runtime.
- *Estado (2026-09-19):* **40,6 MB versionados** (suma de blobs de `graphify-out/` en `HEAD`, `git ls-tree -r -l`), un 45 % más que los 28 MB de agosto; el working tree llega a ~41,7 MB cuando el hook post-commit lo reescribe. La premisa de «excluir `wiki/`» ya no vale: `wiki/` pesa unos KB y el 98 % es `graph.json` (39,9 MB), seguido de `GRAPH_REPORT.md` (0,7 MB).

### [P3] Los dos módulos-dios: `aggregates.py` y `settings.py`
- **Nota:** este ítem estaba **duplicado**. Había una segunda entrada, "Partir los dos módulos-dios: `aggregates.py` y `settings.py`", sobre los mismos dos ficheros y con criterios que se contradecían: una decía "no big-bang, solo dejar de crecer" y la otra "partir por dominio". Fusionados el 2026-08-18 (mismo patrón que la fusión de los `title=` el 2026-08-10). El criterio que sobrevive es el gradual, que es el que el repo ha demostrado que sí ejecuta.
- **Área:** db/repositories/aggregates.py, config/settings.py
- **Problema:** `db/repositories/aggregates.py` son 1.327 líneas y 55 funciones en una sola clase que concentra toda la analítica; `config/settings.py` son 946 líneas con 26 validadores en una clase plana que mezcla ejes ortogonales (BD, ML, LLM, auth, scraper, observabilidad) que ya están conceptualmente separados por `APP_PROFILE`. Son los dos ficheros que todo el mundo tiene que tocar, y donde se concentran los conflictos de merge. (`shared/dto.py`, en contraste, está sano: 620 líneas / 45 clases.)
- **Acceptance criteria:**
  - Una agregación o setting **nuevo** va a un módulo hermano (`aggregates_<área>.py` / settings por dominio) en vez de sumar al monolito.
  - Al tocar un bloque cohesivo existente **por otro motivo**, se evalúa extraerlo en el mismo cambio. El destino de `AggregateRepository` es partido por dominio (overview / geografía / competidores) y el de `Settings` submodelos anidados por eje preservando los nombres de variables de entorno — pero **llegando por partes, con la suite verde entre cada una**, no en un big-bang.
- **Progreso 2026-09-18 (rama worktree-agent-acad4a43a2c0f0bae):** primer módulo hermano de settings, `config/settings_resumen.py` (`ResumenPregenSettings`, de la que hereda `Settings`: mismos nombres de variable de entorno y mismo acceso `settings.X`). Es el patrón para los siguientes settings nuevos. En `aggregates.py` no hubo agregación nueva que mover.
- *Estado (2026-09-19) — las cifras del problema están caducadas y la regla «no crecer» no se ha cumplido:* `db/repositories/aggregates.py` tiene hoy **1.980 líneas** (eran 1.327) y `AggregateRepository` **60 métodos** (eran 55); `config/settings.py`, **1.422 líneas** (eran 946) y **27 validadores**. `shared/dto.py` ya no es el contraejemplo sano: **1.904 líneas y 83 clases** (eran 620 / 45). Medido con `wc -l` y `grep` sobre el árbol.
- **Files de partida:** [db/repositories/aggregates.py](../db/repositories/aggregates.py), [config/settings.py](../config/settings.py)
- **Riesgo:** bajo si se hace oportunista; medio si alguien intenta el big-bang.

### [P3] Migrar la resolución de identidad de `competitors.py` a SQL (union-find + unaccent)
- **Área:** services/analytics/competitors.py, db/repositories/adjudicaciones.py
- **Problema:** Tras mover `overview.py`/`tecnologias.py` a agregación SQL (commit `ab520da`), `competitors.py` quedó híbrido a propósito: sus filtros (fecha/tecnologia/estado/importe_min) ya se empujan a SQL, pero la resolución de identidad de empresa (`_prepare_company_identity`/`_connected_identity_keys`, un connected-components/union-find sobre 5 tokens de identidad por fila) sigue en pandas. Migrarla a SQL necesita `normalize_company`/`normalize_nif` en el motor (NFKD accent-fold + 12+ alternativas regex de sufijo legal), lo que requiere la extensión `unaccent` de Postgres — no habilitada hoy (solo `pg_trgm`/`vector` lo están), y habilitarla exige una migración Alembic (fuera de alcance sin OK humano, AGENTS.md §6).
- **Acceptance criteria:**
  - Extensión `unaccent` habilitada (migración Alembic, requiere confirmación humana).
  - Connected-components de identidad expresado como CTE recursiva en `db/repositories/adjudicaciones.py` (o módulo hermano), con paridad de resultado verificada contra los 17 tests existentes de `tests/test_analytics_competitors.py` (casos: grupo Deloitte curado, joins solo-por-NIF, exclusión de NIF placeholder).
  - `_apply_filters` (red de seguridad redundante añadida en la migración parcial) puede retirarse si el filtrado SQL cubre todos los casos que cubría.
- **Files de partida:** [services/analytics/competitors.py](../services/analytics/competitors.py), [services/normalization.py](../services/normalization.py), [db/repositories/adjudicaciones.py](../db/repositories/adjudicaciones.py), [tests/test_analytics_competitors.py](../tests/test_analytics_competitors.py)
- **Riesgo:** medio — toca una migración de schema (gate humano) y una query recursiva no trivial; mitigado por los 17 tests de caracterización ya existentes.
- **Progreso 2026-09-18 (rama `worktree-agent-af7ab85116eea30b4`) — parcial, el interruptor sigue apagado.** El «Problema» de arriba está desfasado en dos cosas que el código ya desmentía: `unaccent` **sí** está habilitada (`v87_unaccent_extension`, no hace falta otra revisión y no se creó ninguna) y el SQL de la CTE recursiva ya existía sin cablear en `db/repositories/competitor_identity.py`, con su test de paridad por capas. Los tests de `tests/test_analytics_competitors.py` son **15**, no 17. Lo hecho ahora: `resolve_identity_for_rows` reparte **las mismas filas** que ya cargó `load_for_competitors` (con su `LIMIT`), y `services/analytics/competitors.py` la usa cuando `settings.COMPETITORS_IDENTITY_SQL` está activo — **por defecto `False`**, así que el camino de pandas sigue siendo el de producción. La paridad contra los 15 tests se mide reejecutando cada uno con el interruptor encendido (`tests/test_analytics_competitors_identity_sql.py`, capa 5), **no ejecutada**: no hay Postgres en la máquina que la escribió. Falta para cerrar: (1) esa capa en verde en CI; (2) `identity_graph_stats` medido en producción (el cierre de la CTE es cuadrático en el tamaño del componente); (3) encender el interruptor y, tras un ciclo, retirar el union-find de pandas y `_apply_filters`. Aviso para (3): la etiqueta del grupo pasa de raíz del union-find a `MIN(token)`, y es lo que `services/competitive/socios.py` expone como `empresa_key`.

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
- **Progreso 2026-09-24 — 26 → 25:** `services/ml/scoring.py` sale. El upsert de retención, duplicado en las ramas de modelo y de baseline, y la baja real por expediente (`_baja_real`) pasan a `db/repositories/predicciones.py` (`guardar_retencion`, `baja_real_de_expediente`); la división sigue en services. `db/repositories/predicciones.py` entra en `_SCANNED_FILES` del guardrail de dedupe en el mismo cambio, con sus dos purgas como exentas por diseño.
- **Progreso 2026-09-16 — 28 → 26:** `scheduler/kpi_precompute.py` pasa a `db/kpi_precompute.py` (no a `db/repositories/kpi_snapshots.py`, que es de las métricas `ov_*` y advierte que no se mezclen) y `services/competitive/mercado.py` pasa a `db/repositories/mercado.py`, con el `WHERE` construido por `alcance_sql` en vez de interpolación suelta — el candidato «aparte» de más abajo queda cerrado. Equivalencia verificada con un arnés que compara SQL y parámetros contra `HEAD`; `db/repositories/mercado.py` entra en `_SCANNED_FILES` del guardrail de dedupe en el mismo cambio.
- Siguientes candidatos por coste (conteo de `connect(`+`execute(`): `services/ml/calibration.py` (1), `services/entity_resolution.py` (1), `services/competitive/bajas.py` (2), `services/ml/features.py` (2).
- **~~Candidato aparte~~ — hecho el 2026-09-16 (ver progreso arriba).** `services/competitive/mercado.py` concentraba ~12 de los ~30 `# noqa: S608` del repo (conteo del 2026-08-18). Cada supresión está justificada una por una y el idioma de fragmentos constantes está documentado en `services/sql_fragments.py`, así que no es un bug — pero es la mayor densidad de SQL interpolado del proyecto en un solo fichero, y cada filtro nuevo que se añade ahí es otra oportunidad de que un valor entre por concatenación sin que nadie lo note. Al moverlo a `db/`, hacerlo con un builder de `WHERE` testeado en lugar de arrastrar la interpolación tal cual (patrón de `tests/test_adjudicaciones_dedupe_sql.py`, que verifica que los `%s` siguen cuadrando con los parámetros).
- **Orden de olas:** services/ → api/ → scheduler/ → scripts/ (por densidad; `services/` es además el único que viola la capa de dominio de ADR-007)
- **Excepción declarada:** `services/sql_fragments.py` se queda — expone fragmentos SQL constantes pero no ejecuta nada (ADR-022 §3).
- **Acceptance criteria por ola:**
  - `make check` verde tras cada ola.
  - `ruff check --select TID251 --statistics .` monotónamente decreciente (anotar conteo en cada PR).
  - Tests de caracterización donde falten.
  - Estado final: whitelist vacía (`db/**` no la necesita: importar `connect` desde dentro de `db/` está permitido).
- **Files de partida:** `pyproject.toml` (whitelist TID251), `db/repositories/`
- **Riesgo:** medio — toca caminos de datos; mitigado por ratchet como gate y tests de caracterización previos a cada movimiento.


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
- *Estado (2026-09-19):* ese P1 **no existe** en este backlog ni en el archivo, y ya no hace falta: `render.yaml:105` declara `plan: standard` para `tenderflow-api`, con el comentario de que el 2026-08-28 se verificó por la API de Render que el servicio real corre en `standard`. Lo que queda de aquella mitad es reconfirmarlo tras vincular el Blueprint (P2 de `render.yaml`). De paso: `render.yaml` ya no define tres servicios sino cinco (`tenderflow-api`, `tenderflow-worker`, `tenderflow-prometheus`, `tenderflow-alertmanager`, `tenderflow-grafana`), todos en `frankfurt` y ninguno de staging.
- **Riesgo:** bajo técnico, con coste económico — por eso es decisión del usuario.

### [P3] Medir la cobertura de `procedimiento`, `tramitacion` y `peso_precio_pct` y decidir si entran como features
- **Área:** db/repositories/ml_dataset.py, services/ml/features.py
- **Problema:** las tres columnas se persisten desde `v85` y el upsert ya las protege del clobber (ver el ítem cerrado del 2026-09-06), pero siguen fuera de `FEATURE_COLUMNS`: el criterio de aceptación las admitía solo con cobertura real por encima del 50 % y **esa cobertura no se ha medido**. Mientras tanto son datos que se escriben y nadie usa. Una feature NULL en el 90 % de las filas no es neutra: gasta un split del GBM en aprender el patrón de ausencia.
- **Acceptance criteria:**
  - Medida y anotada la cobertura por campo sobre una BD real (o sobre el reprocesado de los ZIP cacheados), con fecha.
  - Si supera el 50 %: los cuatro pasos que enumera `FEATURES_PENDIENTES_COBERTURA` en `services/ml/features.py`, incluido reentrenar y reportar el delta de `mae_p50` contra la versión previa. Si no lo supera, queda escrito el número que lo desaconseja.
- **Files de partida:** [services/ml/features.py](../services/ml/features.py) (`FEATURES_PENDIENTES_COBERTURA`), [db/repositories/ml_dataset.py](../db/repositories/ml_dataset.py)
- **Riesgo:** bajo — el guard de `feature_columns` de `BajaModel` degrada a baseline si se despliega el código sin reentrenar.
- **Progreso parcial (2026-09-18, rama worktree-agent-a3fd0bc81b8a949c2) — la medición existe; el número no.** `ENV=dev python scripts/medir_cobertura_features.py` (o `--json` para archivarlo) imprime, contra la BD de `DATABASE_URL` y solo leyendo, la cobertura de los tres campos sobre dos poblaciones: `dataset_baja` (las filas exactas de entrenamiento, `_sql_agregado`) y `universo_abierto` (lo que puntúa el batch), cada una con total, por `fuente` y por año de publicación, y un veredicto contra el 50 % **solo sobre el total del dataset**. El SQL vive en `MlDatasetRepository.cobertura_features_pendientes`. Tests en `tests/test_medir_cobertura_features.py` (uno contra Postgres, no ejecutado en local). **Falta:** correrlo contra producción, anotar aquí el número con fecha y, según salga, seguir los cuatro pasos o dejar escrito el número que lo desaconseja.

---

## Cerrados

- [2026-09-19] **P2: Remediación axe — reactivar las reglas desactivadas del E2E de accesibilidad** — sin `disableRules` ni `fixme`; últimos rojos en `8a424967` y `0fd5082c`. Ficha en [el archivo](archive/IMPROVEMENT_BACKLOG_CERRADOS.md).
- [2026-09-19] **P2: La experiencia móvil existe pero nadie la diseñó** — los cuatro criterios cumplidos; los rojos móviles del E2E, en `8a424967`. Ficha en [el archivo](archive/IMPROVEMENT_BACKLOG_CERRADOS.md).
- [2026-09-18] **P2: La consola no tiene primer uso** (rama worktree-agent-a37b58d577faad267) — la barra de
  ámbito explica qué es la primera vez (`components/layout/ambito-intro.tsx`,
  se cierra y se recuerda por navegador como `descarte.ts`; cada frase describe
  algo que la barra hace), y cuatro vacíos dicen qué hacer: Radar (quitar la
  tecnología del ámbito o crear una regla), Favoritos (dónde está la estrella,
  con enlace), Reglas (qué hace una regla) y Resultados combinados (aflojar
  criterios). El score ya se explicaba desde el 2026-08-30.
- [2026-09-18] **P3: Migrar los `title=` nativos restantes a `Tooltip`** (rama worktree-agent-a37b58d577faad267)
  — los 36 migrados: controles a `<Tooltip>`, texto truncado y casillas de
  heatmap a `<Pista>` (`components/ui/pista.tsx`), cuyo disparador no es
  focusable para no sumar una parada de tabulación por celda; lo que solo
  vivía en el `title` pasa a texto, `sr-only` o `aria-label`.
  `deudaTitleNativo` vacía y `MAX_TITLE_NATIVO = 0`.
- [2026-09-18] **P3: Scroll edge effects en vez de divisores duros** (rama worktree-agent-a37b58d577faad267) —
  además de la barra de ámbito y la barra móvil, las cabeceras de
  `SpaceShell` y de Resumen pierden el `border-b` fijo: montan su propio
  `ScrollEdgeProvider` (el que scrollea es su cuerpo, no `#main-content`) y el
  borde solo aparece con contenido debajo. Con `bleed` se conserva el borde.

**Cerrados el 2026-09-06 por la reconciliación O0.5** — ficha completa de cada
uno en [el archivo](archive/IMPROVEMENT_BACKLOG_CERRADOS.md), que es donde
AGENTS.md §0 manda que vivan los cerrados. Ninguno se cerró por lo que decía la
cabecera de este fichero: los seis se comprobaron contra el código.

- [P1] Aprobar un acceso es editar variables de entorno a mano — RFC 242, `v95_access_grants`, `db/access_grants.py` y las rutas `/admin/solicitudes-acceso/grants` con auditoría.
- [P2] Persistir procedimiento, tramitación y peso del precio — `v85` + `db/upsert.py`; entrar en `FEATURE_COLUMNS` sigue abierto como P3 propio, y se explica por qué.
- [P2] `HistGradientBoosting` revienta con una feature todo-NaN — `_columnas_observadas` + `tests/test_s3_feature_todo_nan.py`.
- [P2] Migrar las llamadas del frontend al cliente OpenAPI tipado — sin `fetch("/api/…")` crudo fuera de `lib/`, con regla ESLint que lo impide.
- [P3] Vigilar el crecimiento de `predicciones_baja` — purga por antigüedad en el job de ML.
- Modelos NIM de razonamiento sin `chat_template_kwargs` — arreglado en `9a6014b`; nunca llegó a ser ítem abierto, y se anota para que el backlog refleje el código.
- [2026-09-18, rama `worktree-agent-acc2389c11c7f60d4`] **[P1] Cobertura de tests de las
  páginas del frontend** — los tres criterios, medidos. (1) De los tres flujos «sin cubrir»,
  dos ya lo estaban cuando se revisó: `use-watchlist-items` (100 % de sentencias) y
  `ask-stream.ts` (96,9 %); el que faltaba de verdad, los filtros nuqs usados desde una
  página, lo cubren ahora los tests de `mercado/_hooks/use-tecnologias-view`,
  `use-organos-view` y `radar/_hooks/use-radar-consola` con el ámbito **real** (adaptador de
  pruebas de nuqs, sin doblar `useFilterParams`) y el test de paridad
  `lib/__tests__/filter-params.test.tsx`. (2) La lógica de `tecnologias`, `organos` y `radar`
  ya estaba en `_hooks/`; le faltaban tests, y los tres hooks quedan en 97–100 % de
  sentencias. (3) `npx vitest run --coverage` **terminó en local por primera vez desde
  2026-08-10** (199 ficheros, 2.198 tests): global 56,45/48,45/51,45/57,15 y `src/app/**`
  39,27/34,54/34,44/39,47. `web/vitest.config.ts` sube los globales de 38/28/35/39 a
  54/46/49/55, `src/app/**` gana su piso de sentencias (37/32/32/37) y los pisos por carpeta
  suben donde había margen, sin bajar ninguno. Hallazgo sin arreglar: en la vista
  Tecnologías, con `?tecnologia=` en el ámbito, el detalle de la tecnología elegida viaja con
  la del ámbito (`useFilteredQuery` hace ganar al filtro global sobre `extraParams`).
- [2026-09-07] **Barrido de ortografía castellana en las cadenas visibles**
  — cerrado al medirlo (C7.8): **cero** cadenas de UI sin tilde y **cero** `...`
  donde corresponde `…`. La ola anterior lo había cerrado y el backlog no se
  actualizó. `scripts/check_ortografia_ui.py` lo mantiene cerrado en CI, mirando
  solo texto JSX visible y props de copy — un grep sobre el fichero entero
  marcaría `"tecnologia"` y `"organo"`, que aquí son **nombres de campo de la
  API** y acentuarlos rompería las peticiones.
  El primer borrador de ese script daba 38 hallazgos y **los 38 eran correctos**:
  llevaba en la lista los plurales en `-ciones`, que no llevan tilde
  («licitación» → «licitaciones»). La lista quedó con los singulares agudos y
  con los plurales que sí la conservan («órganos», «tecnologías»).
- [2026-09-18] **Cerrados en la rama `worktree-agent-ac2127b7dcd3fc315`:**
  - P3 «Documentar `FRONTEND_URL` y `SENTRY_DSN` en `.env.example`» — documentadas, junto con las `DOCUMENT_BLOB_*` de S8.1; `_DOCUMENTACION_PENDIENTE` queda vacía y `scripts/check_env_parity.py` pasa.
  - P3 «Cuatro módulos citan un RFC de retirada de exports que no existe» — `docs/rfc/2026-09-03-rfc-retirada-exports-asincronos.md` reconstruido desde D7, `9207bde9` y #265; índice regenerado.
  - P3 «Decidir el destino de los tests tautológicos» — los dos de argon2 se reescriben en `tests/test_auth_core.py` contra la librería real y la rama sin argon2; el de `hasattr` sobre un `Protocol` se borra; `tests/test_TODO_review_tautologico.py` desaparece.
  - P3 «Suites propias para `services/investigador/` y `extraction_runs`» — `tests/test_investigador_search_engine.py` y `tests/test_extraction_runs.py` (el test `_bd` necesita Postgres).

- [2026-09-18] **P2: Contrato de paginación común para la API** (rama
  worktree-agent-acad4a43a2c0f0bae) — `PaginatedResponse`/`CursorPaginatedResponse`
  ya vivían en `shared/dto.py`; faltaba la otra mitad: `api/pagination.py`
  (`PageParams` + `pagina(default)`) declara `limit`/`offset` una sola vez con
  `MAX_PAGE_LIMIT` como tope único. Primera ola: las siete rutas que ya paginaban
  por offset (licitaciones, adjudicaciones, adjudicaciones de empresa, pursuits,
  comentarios, Próximas, empresas); mismos parámetros y misma respuesta, con el tope
  ensanchado de 200 a 500 donde era 200. `trends` ya exponía el roll-up `group_by`
  (day/week/month) y `serie_truncada` documentados en el DTO. Siguientes olas: las
  rutas con solo `limit` que devuelven listas.
- [2026-09-18] **P3: El embudo del Resumen mide sus porcentajes contra todo el
  corpus** (misma rama) — decidido: los cinco escalones (PUB, EV, RES, ADJ, ANUL)
  se miden contra su propia suma y suman 100; lo demás (PRE, AGR, EJEC, CPM, OTROS)
  sigue listado con `en_embudo=false` y `pct` sobre el ámbito. `OverviewResult`
  gana `funnel_denominador` y `fuera_del_embudo`. Cambio de semántica de
  `FunnelStep.pct` documentado en el DTO (AGENTS §3.5). El frontend no pinta
  `funnel_estados`, así que no hubo rótulo que cambiar.
- [2026-09-18] **P3: Unificar la definición de «Calientes»** (misma rama) —
  decidido: el Resumen mantiene su heurística (importe ≥ P75, abierta y en plazo)
  con el nombre que ya enseña la UI, «Grandes en plazo»; la banda `Caliente` del
  score queda para el Radar. Los campos `ResumenHoyResult.calientes`,
  `HoyCounters.calientes` y `OverviewResult.calientes_hoy` no se renombran y llevan
  la definición en su descripción OpenAPI (`shared.dto.DESCRIPCION_GRANDES_EN_PLAZO`).
- [2026-09-18] **P3: Pre-generar el resumen IA nocturno para licitaciones
  calientes** (misma rama) — fase 5 de `scheduler/jobs/documentos_embeddings.py`,
  gated por `RESUMEN_PREGEN_ENABLED` (off; `config/settings_resumen.py`): hasta
  `RESUMEN_PREGEN_BATCH` licitaciones abiertas —seguidas, banda `Caliente`, publicadas
  hoy— sin entrada vigente en el caché del resumen. BudgetGuard antes de cada una,
  corte por credencial rechazada, y salto entero sin caché compartida (Redis).
  Clave, prompt y contexto compartidos con la ruta en `services/rag/resumen.py`.
  **Pendiente de decisión humana para que sirva en Actions:** `pliegos.yml` no
  propaga `REDIS_URL` (a propósito, por el gate de presupuesto de fichas), así que
  en ese plano la fase se salta; activarla allí exige propagar `REDIS_URL` y la
  variable `RESUMEN_PREGEN_ENABLED`.
- [2026-09-14] **P2: cada re-ingesta nuleaba las cuatro columnas ML, y `tech_signal_merge`
  lo curaba a ciegas cada 4 h** — decidido: el clobber se corta en origen. `ml_proba`,
  `ml_tecnologias`, `ml_proba_max` y `ml_tech_principal` entran en
  `_LIC_COALESCE_UPDATE_FIELDS` (`db/upsert.py`): el `None` de un conector es «sin opinión», y
  los pasos ML siguen escribiendo por UPDATE explícito. `merge_doc_signals()` sin ids deja de
  barrer la tabla: `list_signals_for_merge` acota a licitaciones con señal sin `merged_at` o con
  resumen ML a NULL o sin la tecnología detectada, y devuelve
  `licitaciones_candidatas`/`licitaciones_reparadas`, que el paso loguea — «cero reparaciones en
  siete días» se lee ahí. Ficha completa en
  [el archivo](archive/IMPROVEMENT_BACKLOG_CERRADOS.md).
- [2026-09-18] **P2: Separar los requirements de la API de los del pipeline/ML**
  — rama `worktree-agent-aa37c7b64b746caaa` (sin PR). `requirements-api.txt`
  (63 pines) y `requirements-pipeline.txt` (79) compilados con hashes por
  `make lock`, con `--constraint requirements.txt` para que los pines coincidan
  con los que prueba el CI (`scripts/check_requirements_sync.py` lo verifica y
  además que el lock de la API no traiga nada solo-pipeline).
  `docker/Dockerfile.api` instala por defecto el de la API; `ARG
  REQUIREMENTS_FILE` da la variante del pipeline, que es la que usa
  `tenderflow-worker` en render.yaml y la vuelta atrás sin tocar código. Salen
  de la imagen de la API scikit-learn, scipy, joblib, statsmodels, networkx y
  lxml. Smoke por entrypoint en `tests/test_unit_api_imagen_slim.py` (la API
  arranca en un proceso que solo puede importar su lockfile; el worker, el del
  pipeline) y `ci.yml::docker-build` construye y prueba las dos variantes y
  publica su tamaño. La medición destapó un import implícito: `/publico/cobertura`
  arrastraba lxml vía `scraper.connectors` (arreglado con re-export diferido).
  `/explain` y `/analytics/clusters` responden 503 sin sklearn; su destino es la
  RFC [2026-09-18-rfc-explain-fuera-del-proceso-api](rfc/2026-09-18-rfc-explain-fuera-del-proceso-api.md)
  (`review`), que deja la decisión de desplegar la imagen reducida al mantenedor.
  **No verificado:** el build Docker real (el daemon no estaba levantado en la
  máquina que lo hizo; lo cubre el job de CI) y que Render pase
  `REQUIREMENTS_FILE` como build arg.
- [2026-09-18, rama worktree-agent-a3fd0bc81b8a949c2] **P3: un solo transporte para bajar
  assets de la Release** — `shared/model_artifacts.py::_download_release_asset` delega en
  `shared.release_assets` (`fetch_latest_release` → `find_asset_id` → `download_asset`): HTTPS
  pinned, allowlist por salto y sin reenviar el token al CDN. `requests` sale del módulo. La
  verificación del sha256 contra `model_versions` no se tocó: sigue en `resolve_active_artifact`,
  después de materializar, igual para bucket y Release. Tests nuevos en
  `tests/test_model_artifacts.py` (delegación, asset ausente, Release inaccesible, y un guard AST
  de que `requests` no vuelve).
- [2026-09-18, rama worktree-agent-a3fd0bc81b8a949c2] **P2: calibrar los umbrales de la
  auditoría de verdad del dato** — con los `domain-truth.json` de siete ejecuciones
  programadas (12→18/09, descargados con `gh run download`, artefacto
  `domain-truth-measurements`). `fecha_limite` por fuente ya se había calibrado en C4.5
  (2026-09-06); ahora `placsp` baja a 81,9 % (su límite estaba topado en 100 y no podía
  saltar), `ted` a 65,9 %, la UTE de 8 % a 0,02 % (medido las siete veces) y el delta de
  baja de 5 a 1,12 puntos. Histórico por día en el docstring de
  `scripts/audit_domain_truth.py`. De la serie sale un P2 nuevo: `importe_tipo` sin base
  declarada viola su umbral a diario y crece.


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
