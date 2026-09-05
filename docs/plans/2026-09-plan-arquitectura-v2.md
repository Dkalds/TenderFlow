---
tags: [plan, arquitectura, producto, multi-agente]
---

# Plan de arquitectura y producto 2026-09 v2 — cerrar los bucles abiertos

Redactado el 2026-09-05 a partir de una revisión completa del repositorio:
el código de `api/`, `services/`, `db/`, `scraper/`, `scheduler/`, `llm/` y
`web/`, los 21 workflows, el backlog, la auditoría UX, los RFC y el estado de
ejecución del plan de septiembre. Todo lo que aquí se afirma se comprobó contra
el árbol de la rama `claude/app-architecture-review-d3vcog` (base `master` =
`17169ce`) y lleva su referencia. Lo que no se pudo comprobar desde esa sesión,
que es el estado real de producción, se marca como tal.

Sucede a [2026-09-plan-arquitectura.md](2026-09-plan-arquitectura.md), cuyo
§8 es el punto de partida: nada de lo que allí consta como hecho se repite
aquí, y los tres ítems de frontend que quedaron a medias (S5.1, S5.2 y S5.9)
se citan desde el stream S7 con sus criterios originales, sin redefinirlos.

**Estado: PROPUESTO el 2026-09-05.** Nada de este documento está implementado.
Mismo contrato que sus predecesores: cada stream se ejecuta en su propia rama
por un agente independiente, este documento es la fuente única de alcance y
criterios de aceptación, y un agente que toma un stream trabaja **solo** los
ficheros de ese stream.

## 0. Alcance y método

**Qué cubre.** Las funcionalidades que faltan para cumplir la promesa de la
portada («dónde pujar, a qué precio, contra quién»), y las modificaciones de
arquitectura y operación sin las que esas funcionalidades no se sostienen.

**Qué queda fuera.** El backup y el restore drill, por decisión del mantenedor
del 2026-09-05, igual que en el plan anterior (§0). No aparecen en ninguna
ola, métrica ni gate de este documento. Tampoco se repite lo que el plan de
septiembre dio por hecho en su §8 (S1–S4, S6, S7 y la Ola 0).

**Convenciones.** Esfuerzo **S** menos de un día de agente · **M** uno a tres
días · **L** varias PRs. Los gates de AGENTS.md §6 se marcan **[§6]** y
requieren OK explícito salvo que D20 los pre-autorice. Un criterio de
aceptación entra solo si se puede verificar con un comando, un test o una
consulta; los que exigen producción lo dicen. Las cifras llevan fecha de
medición y no se corrigen a mano: se vuelven a medir.

### La tesis

TenderFlow ya no es un observatorio. Tiene radar, oportunidades por
organización, ficha del pliego con evidencia, precio por escenarios y
competencia, y una disciplina de ingeniería poco habitual: tipado estricto,
ratchets que solo encogen, contrato OpenAPI sin operaciones opacas, ADR-014
bloqueante en CI y un gate de promoción de modelos sobre un golden set humano.

El problema no es falta de rigor ni de superficie, sino lo contrario: **hay más
superficie que cimientos**. El valor siguiente no sale de otro corte analítico
sino de cerrar cuatro bucles que hoy están abiertos:

1. **Operación.** Producción va por detrás del repo, conviven dos caminos de
   despliegue y las alertas críticas no tienen receptor.
2. **Identidad y capacidad de la organización.** Una organización es un nombre
   y una lista de tecnologías; sin NIF ni capacidad, la ficha del pliego no
   tiene contra qué contrastarse y el cierre de una oportunidad no sabe quién
   ganó.
3. **Eventos y salida.** Siete almacenes con forma de evento, ninguno es el
   backbone, y el equipo solo se entera por email o abriendo la consola.
4. **Etiquetas del ML.** Hay cinco modelos y seis mecanismos de drift sobre un
   golden set de veintisiete ejemplos y un clasificador que no puede
   reentrenarse.

Cada ola de este plan cierra uno de esos bucles antes de abrir superficie
nueva. Lo que no cierra ninguno queda en §8.

## 1. Hechos verificados (2026-09-05)

Los agentes ejecutores asumen ESTO, no lo que digan docs anteriores.

### Operación y despliegue

1. **Producción va por detrás del schema.** Según el §8 del plan de septiembre
   (04-09), producción estaba en `v97` con la cabeza del repo en `v102`, y las
   cuatro revisiones `v99`–`v102` no se han aplicado en ninguna base real.
   Esta revisión no tiene acceso a producción y **no lo re-verifica**.
   `GET /health/ready` ya compara la revisión aplicada con las cabezas del
   repo (`api/routes/health.py:120-163`).
2. **Dos caminos de despliegue conviven.** La cabecera de `render.yaml`
   declara que el servicio se creó a mano, que `autoDeploy` está activo y que
   `healthCheckPath` está sin verificar; `.github/workflows/deploy.yml:5`
   asume `autoDeploy: false` y dispara el deploy hook (`deploy.yml:59`). Un
   push a `master` puede desplegar dos veces, una de ellas con CI en rojo.
3. **Alertas sin receptor, con la solución escrita.** Existen
   `docker/Dockerfile.alertmanager` y `observability/alertmanager.yml`; el
   servicio no existe en Render (D5 del plan anterior, sin resolver).
4. **Mínimo privilegio en BD, escrito y sin ejecutar.** `scripts/setup_pg_roles.sql`
   prepara el rol `tenderflow_app`; no se ha ejecutado, `DATABASE_ADMIN_URL`
   no existe y la RLS sigue inerte (backlog P1 F3d; plan anterior S6.4).
5. **Decisiones que el código ya resolvió y nadie anotó.** D1–D9 siguen sin
   registrar como resueltas. Pero D2 está resuelta de facto:
   `.github/workflows/train-tech.yml` entrena y publica el clasificador
   multi-tecnología con cron mensual. Y tres ítems abiertos del backlog están
   cerrados por código: «Persistir procedimiento, tramitación y peso del
   precio» (revisión `v85_lic_procedimiento_tramitacion` y `db/upsert.py:249`),
   «Aprobar un acceso es editar variables de entorno» (revisión
   `v95_access_grants`, `db/access_grants.py` y las rutas de
   `/admin/solicitudes-acceso/grants`) y los cuatro que la propia cabecera del
   backlog marca como cerrados y siguen listados en P2/P3.

### API y superficie

6. **Endpoints que la web no puede usar.** `GET /licitaciones/cursor`, el
   listado recomendado, exige `require_api_key`
   (`api/routes/licitaciones.py:339-343`); lo mismo `/explain`, `/tech-scores`
   y `/bulk-get`. `POST /models/{name}/activate/{version}` y
   `GET /security/audit/verify` exigen `require_scope("admin")`, así que un
   administrador con sesión no puede activar un modelo desde el navegador.
7. **La búsqueda semántica no es semántica.** `POST /search/semantic` ejecuta
   `tsvector` con fallback `LIKE` y declara `alpha`/`embedding_model` como
   legacy sin efecto (`api/routes/search.py:125-133`). El Investigador pinta
   un deslizador «Alpha (FAISS vs FTS5)»
   (`web/src/app/(dashboard)/investigador/page.tsx:330`) que el backend
   ignora. La fusión RRF con pgvector existe (`db/search_backend.py:320`) y
   solo la usa el RAG (`services/licitaciones.py:222`).
8. **El ratchet OpenAPI tiene un agujero.** `_is_opaque` solo mira el objeto
   de primer nivel y no recorre arrays
   (`scripts/check_openapi_contract.py:51-60`). Tres operaciones publicadas
   devuelven `list[dict[str, Any]]` y generan `unknown[]` en el cliente:
   `GET /me/keys` (`api/routes/me.py:242`), `GET /models/{name}/versions`
   (`api/routes/models.py:52`) y `GET /webhooks` (`api/routes/webhooks.py:366`).
9. **Tres endpoints de analítica sin consumidor** en `web/src`:
   `/analytics/compare-periods`, `/analytics/resumen/sankey` y
   `/analytics/resumen/top` (`web/src/lib/analytics.ts:40-46`).

### Eventos, notificaciones y equipo

10. **Notificaciones: email e in-app, y nada más.** Los webhooks exigen
    `require_admin` en todas sus rutas y `_VALID_EVENTS` tiene cuatro tipos,
    todos de watchlist o de solicitudes de acceso
    (`api/routes/webhooks.py:51-57`). Cero referencias a Slack o Teams en el
    repositorio.
11. **Siete almacenes con forma de evento y ningún backbone.**
    `pursuit_events`, `contrato_eventos`, `licitaciones_history`,
    `user_notifications`, `pending_digests`, `webhook_deliveries` y
    `domain_events`. La tabla de event sourcing `domain_events` solo la
    escriben `services/tech_signal.py:22` y la invalidación de caché
    (`db/events.py:137`).
12. **Cambios en expedientes seguidos sin alerta.** `licitaciones_history`
    guarda `changed_fields`, pero solo `services/contract_events.py` los lee
    para derivar eventos de contrato; ningún productor de notificaciones los
    consume. Los recordatorios cubren únicamente vencimientos
    (`services/deadline_reminders.py`).
13. **Invitar exige cuenta previa.** `add_member_by_email` rechaza un email
    sin cuenta activa (`services/organizations.py:117-137`) aunque
    `organization_memberships.status` admite `invited` desde `v61`. El único
    OAuth es Google. El producto sirve desde un subdominio de Vercel sin
    dominio propio (UX_AUDIT, superficie pública).
14. **La organización no sabe quién es.** `OrganizationSettings` solo tiene
    `tecnologias` (`shared/dto.py:644-667`). No hay NIF, y
    `PursuitAdjudicacionDetectada` pide confirmación humana porque «el sistema
    no conoce el NIF de la organización» (`shared/dto.py:795-803`).

### Producto

15. **Una oportunidad por expediente, nunca por lote.** `pursuits` es única
    por `(organization_id, licitacion_id)` (`uq_pursuits_org_licitacion` en
    `v61`; `db/repositories/pursuits.py:109`). Los lotes existen desde `v65` y
    `predicciones_baja` ya los distingue (`v86`).
16. **El Radar guarda su nota y nadie la lee.** `score_al_abrir` y
    `banda_al_abrir` se persisten desde `v93` (`db/repositories/pursuits.py:86-120`)
    y ningún módulo de producción los consulta: grep en `api/`, `services/`,
    `db/`, `scheduler/` y `scripts/` solo encuentra la escritura.
17. **Reglas de watchlist estrechas.** `WatchlistRuleBody` admite `nombre`,
    `keyword`, `cpv`, `min_importe`, `ccaa`, `frequency`, `active`,
    `organization_id` y `visibility` (`api/routes/watchlist_rules.py:69-80`).
    Sin tecnología, órgano, procedimiento, banda de score ni plazo.
18. **Seis primitivas de seguimiento.** Favoritos (tres endpoints), empresas
    vigiladas (tres, `api/routes/competitive.py:409-445`), reglas (siete),
    descartes del radar (tres), vistas guardadas (tres) y perfil de scoring
    (tres): 22 endpoints y al menos seis tablas para decir «esto me importa».
19. **Documentos: solo PDF con texto y texto plano.**
    `_SUPPORTED_CONTENT_TYPES` (`scraper/document_fetcher.py:31`); un PDF
    escaneado termina en error sin OCR (`:141`); el binario no se conserva
    (docstring del módulo).

### Plataforma y datos

20. **Identidad derivada del email.** `user_key` aparece en 26 ficheros de
    `db/` y 34 de `api/` + `services/` (grep `-rl`, 2026-09-05).
21. **Sin cola de trabajo.** El cierre post-ingesta son quince pasos
    secuenciales en `CANONICAL_STEPS` (`scheduler/pipeline_runs.py:43-58`)
    dentro de un job de Actions cada cuatro horas. La extracción asíncrona de
    la ficha corre en `BackgroundTasks` de la API
    (`api/routes/licitaciones.py:717-729`) con un drenado de 30 s al apagar
    (`api/app.py:154-168`): con `autoDeploy` activo, un despliegue la mata. El
    precalentamiento analítico está deshabilitado tras el OOM del 2026-08-02 y
    los agregados siguen cargando tablas completas en pandas de forma lazy
    (`api/app.py:123-130`). `API_ML_TOKENS = 2`.
22. **ML: etiquetas finas bajo modelos anchos.** El clasificador SAP no puede
    reentrenarse porque el corpus PSCP ahoga el dataset (backlog P2); el
    golden set tiene 27 ejemplos (backlog P1); `TechnologyClassifier` entrena
    con etiquetas circulares porque `train_from_db` no lee las columnas humana
    y LLM (`scraper/tech_classifier.py:29-34`); los modelos NIM de razonamiento
    pueden vaciar el stream porque el cliente no envía `chat_template_kwargs`
    (`llm/client.py:57-62`); baja v2 y retención v1 están registrados y no son
    activables (backlog P2).
23. **Código muerto conocido.** `services/clusters.py` (envoltorio sin
    referencias de producción) y `db/feature_store.py` (cero referencias fuera
    de la migración base).
24. **Frontend.** Doce ficheros de `web/src/app` superan las 300 líneas
    (tabla abajo). No hay i18n en `web/` (solo `lang="es"`), ni librería de
    formularios, ni service worker (el PWA es solo el manifest). Los
    inspectores de Radar y Detalle solo existen desde `xl`
    (`radar/page.tsx:801-808`). Las feature flags se administran en `/ops` y
    ninguna vista las lee: fuera de `ops/` solo aparecen como nombre de ruta
    heredada en `lib/navigation.ts` y `lib/space-views.ts`.
25. **Documentación que el código desmiente.** `docs/database-schema.md`
    describe SQLite, FTS5 y las versiones v1–v20 cuando Alembic va por `v102`.
    Cinco RFC figuran abiertos estando implementados: `242`, `243`,
    `2026-09-02-rfc-enlaces-firmados-sin-sesion`,
    `2026-06-30-rfc-retrofit-pipeline-placsp-connector` y
    `2026-06-16-rfc-meta-integridad-analitica-frontend` (graduado a ADR-014).
    `2026-07-21-rfc-relaciones-estructura-mercado` apunta a tres ficheros
    borrados.

### Cifras de partida

| Magnitud | Valor | Medido |
|---|---|---|
| Filas en `licitaciones` en estado `AGR` (avisos agregados) | 645.664 | backlog, producción 2026-09-03 |
| Expedientes de la superficie pública antes de `v98` | 417.182 | backlog, producción 2026-09-03 |
| Dataset entrenable del clasificador SAP | 21.963 filas, 4.928 positivos | backlog P2 |
| Corpus PSCP | 683 k filas, 0,46 % positivos | backlog P2 |
| Endpoints / espacios de consola | 173 / 14 | `docs/STATUS.md` 2026-09-04, `lib/console-spaces.ts` |
| Ficheros con `user_key` | 60 | grep 2026-09-05 |
| Ficheros de `web/src/app` con más de 300 líneas | 12 | `wc -l` 2026-09-05 |

Los doce ficheros, medidos el 2026-09-05 (`wc -l`, sin tests):

| Fichero | Líneas |
|---|---:|
| `detalle/page.tsx` | 952 |
| `competencia/_components/competidores-view.tsx` | 890 |
| `ops/_components/active-learning-view.tsx` | 884 |
| `radar/page.tsx` | 831 |
| `mi-perfil/page.tsx` | 764 |
| `mercado/_components/tecnologias-view.tsx` | 742 |
| `mi-pipeline/_components/agenda-view.tsx` | 708 |
| `ops/_components/administracion-view.tsx` | 689 |
| `mercado/_components/organos-view.tsx` | 680 |
| `mercado/_components/proyectos-modulos-view.tsx` | 626 |
| `investigador/page.tsx` | 618 |
| `empresas/page.tsx` | 579 |

## 2. Olas

- **Ola 0 — Operación, decisiones y honestidad.** Sin código de producto.
  Objetivo: producción igual al repo, un solo camino de despliegue, alertas que
  llegan a alguien, ninguna superficie que prometa lo que el backend no hace, y
  documentación que el código no desmienta.
- **Ola 1 — Streams paralelos S1..S8.** Cada uno cierra un bucle de la tesis.
  Trabajo sin gate o con gate pre-autorizado en D20.
- **Ola 2 — Lo que depende de una decisión o de una migración grande (T1..T7).**
  Cada ítem lleva la decisión o el stream que lo desbloquea.

Ningún stream de Ola 1 arranca hasta que O0.1, O0.2 y O0.5 estén cerrados: no
tiene sentido construir sobre un schema que producción no tiene, ni desplegar
por dos caminos, ni empezar ítems cuya decisión sigue abierta.

## 3. Decisiones del mantenedor

### Heredadas del plan de septiembre

D1–D9 siguen sin registrarse como resueltas. Este plan no las redefine; O0.5
las cierra o las retira. Dos ya están resueltas en el código y solo falta
anotarlo: **D2** (publicar `TechnologyClassifier`: `train-tech.yml` existe) y
el ítem del backlog sobre procedimiento y tramitación (`v85`). **D7** (export
asíncrono) se ejecutó por la vía «retirar» el 2026-09-03.

### Nuevas

| Id | Decisión | Desbloquea |
|---|---|---|
| D11 | **Perfil de capacidad.** ¿Vive en `organizations.settings_json` (sin migración) o en tablas propias (`organization_nifs`, `organization_capabilities`)? Propuesta: tablas propias, porque el cierre por NIF y el contraste de solvencia se resuelven en SQL y un JSON no se indexa ni se valida. | S2 |
| D12 | **Oportunidad por lote.** ¿`pursuits.lote_id` nullable con dos únicos parciales (patrón `v65` de adjudicaciones) o entidad hija `pursuit_lotes`? Propuesta: `lote_id` nullable; `NULL` significa expediente completo y las filas existentes no cambian. | S3 |
| D13 | **Teams y Slack.** ¿Plantillas de payload sobre el webhook genérico existente, o integraciones nativas con OAuth de cada plataforma? Propuesta: plantillas (`json`, `slack_blocks`, `teams_adaptive_card`) y webhooks que pueda crear un miembro dentro de su organización, no solo el administrador global. | S4 |
| D14 | **Worker.** ¿Un servicio `worker` en Render (coste de un servicio más) o consumir la cola desde el propio job de Actions cada cuatro horas? Propuesta: worker en Render para lo que pide un usuario (ficha, resumen, export) y Actions para lo programado; la cola es la misma tabla. | S5 |
| D15 | **Búsqueda semántica.** ¿Servir la fusión RRF que ya existe en `/search/semantic`, o retirar el deslizador y renombrar el endpoint (**RFC**: cambia la semántica del contrato)? Propuesta: servir. | O0.6 |
| D16 | **Cobertura fuera de PLACSP y TED.** Contratos menores, BOE y los portales de Madrid, Andalucía y Valencia. Propuesta: declararlos fuera de alcance en `/cobertura` con fecha, y abrir un conector solo cuando una organización lo pida por escrito. | T7 |
| D17 | **OIDC.** ¿Microsoft Entra ID multi-tenant (`common`) con allowlist por dominio, o un registro por tenant de cliente? Propuesta: multi-tenant reutilizando `OAUTH_ALLOWED_DOMAINS` y `access_grants`, que ya existen. | S1 |
| D18 | **Identidad.** ¿Migrar `user_key` → `user_id` con columna doble y lectura dual, o mantener `user_key` y solo prohibirla en código nuevo? Propuesta: ratchet ahora (S1.4) y migración aditiva por olas (T4). | S1, T4 |
| D19 | **Retirada de endpoints.** Los tres de analítica sin consumidor y el listado por offset. Es un cambio breaking del contrato público y exige **RFC**. Propuesta: `deprecated=True` ahora y RFC de retirada con fecha a 90 días. | O0.6 |
| D20 | **Gates §6 pre-autorizados para este plan.** Migraciones `v103+` de S2, S3, S4 y S5 en los términos de cada ítem; edición de `deploy.yml`, `ci.yml`, `pliegos.yml`, `scrape-daily.yml` y `render.yaml` en los términos de O0.2, O0.7, S5 y S8; `.env.example` para las variables que S1, S5 y S8 declaran; dependencias de S7.2 y S8.2. Todo lo demás pide OK puntual. | O0, S1–S8 |

Mientras D11–D19 no estén cerradas, los ítems que las citan no se empiezan. Un
agente que necesite una decisión no tomada la deja escrita en el PR y se
detiene ahí.

---

## 4. Ola 0 — Operación, decisiones y honestidad

Orden sugerido: O0.1, O0.2 y O0.5 son acciones del mantenedor y van primero;
O0.3 y O0.4 en ventana; O0.6 y O0.7 son paralelos y no tocan producción.

### O0.1 — Producción al día de schema

**Qué.** Lanzar `migrate.yml` con `mode=plan` y luego `mode=apply` hasta
`v102`, con `make audit-truth-check` antes y después para medir el delta que
el plan anterior dejó sin medir (§6bis F2).

**Ficheros.** Acción del mantenedor. `scripts/audit_domain_truth.py`.
**Esfuerzo / gate.** S · acción humana: `migrate.yml` es `workflow_dispatch`
a propósito.

**Aceptación.**
- `GET /health/ready` en producción devuelve `schema: ok (v102)`.
- El delta de `make audit-truth-check` (antes/después) está anotado en el ítem
  del backlog «La portada cita el tamaño del censo bajo un titular que lo
  niega», y ese ítem pasa a Cerrados.
- `GET /publico/sitemap/resumen` en producción devuelve la cifra del universo
  tecnológico, no el censo.

### O0.2 — Un solo camino de despliegue

**Qué.** Cerrar D4: o se vincula el Blueprint y `render.yaml` manda (con
`autoDeploy: false`, `healthCheckPath` y `deploy.yml` como único disparador),
o se declara documental, se replica a mano `healthCheckPath`, se deja
`autoDeploy` activo y **se borra `deploy.yml`**. Lo que no puede seguir es la
convivencia de los dos.

**Ficheros.** `render.yaml`, `.github/workflows/deploy.yml`, dashboard de
Render.
**Esfuerzo / gate.** S · **[§6]** workflow, pre-autorizado en D20; el
dashboard es acción humana.

**Aceptación.**
- Un push a `master` produce exactamente un deploy en Render, comprobado en el
  dashboard durante siete días.
- La cabecera de `render.yaml` lleva fecha de verificación y los valores
  reales de Blueprint, `autoDeploy`, `plan` y `healthCheckPath`.
- `deploy.yml` existe solo si `autoDeploy` está apagado.
- `smoke.yml` verde en las 96 ejecuciones siguientes al cambio (24 h).

### O0.3 — Alertas que llegan (D5)

**Qué.** Crear el servicio Alertmanager en Render desde
`docker/Dockerfile.alertmanager`, activar `alerting:` en
`observability/prometheus.render.yml` y comprobar que la regla `Watchdog`
llega.

**Ficheros.** `observability/prometheus.render.yml`, `render.yaml`,
`docs/runbooks/observability-alerts.md`.
**Esfuerzo / gate.** S · acción humana en Render.

**Aceptación.**
- La alerta `Watchdog` llega al receptor de email en cada intervalo durante
  siete días seguidos.
- `alert_delivery_failed_total` (`observability/alerts.py`) es visible en
  Grafana y vale cero en esa ventana.
- `docs/runbooks/observability-alerts.md` describe el plano real con fecha.

### O0.4 — Mínimo privilegio en BD (S6.4 del plan anterior)

**Qué.** Ejecutar `scripts/setup_pg_roles.sql`, crear `DATABASE_ADMIN_URL`
solo para `migrate.yml`, rotar `DATABASE_URL` al rol `tenderflow_app` y
comprobar que la RLS deja de ser inerte.

**Ficheros.** `config/settings.py`, `.env.example`, `.github/workflows/migrate.yml`,
`docs/runbooks/persistence-tripwires.md`.
**Esfuerzo / gate.** S · **[§6]** `.env.example` y workflow, pre-autorizados
en D20; la rotación es acción humana en ventana.

**Aceptación.**
- Con el rol de la API, `CREATE TABLE` en `psql` falla con `permission denied`
  y `alembic upgrade head` falla.
- Con el rol de la API y sin fijar tenant, una consulta sobre una tabla con
  RLS devuelve cero filas de otra organización. El procedimiento queda escrito
  en `docs/runbooks/persistence-tripwires.md` con fecha.
- `migrate.yml` usa `DATABASE_ADMIN_URL`; la API no la conoce.

### O0.5 — Decisiones y backlog reconciliados

**Qué.** Cerrar o retirar D1–D9 y D11–D19 con fecha; mover a Cerrados los
ítems del backlog que el código ya resolvió (hecho 5).

**Ficheros.** `docs/plans/2026-09-plan-arquitectura.md` §3, este documento
§3, `docs/IMPROVEMENT_BACKLOG.md`, `docs/archive/IMPROVEMENT_BACKLOG_CERRADOS.md`.
**Esfuerzo / gate.** S · decisiones del mantenedor.

**Aceptación.**
- La tabla §3 del plan de septiembre tiene columna «Resuelta» con fecha en las
  nueve filas; la tabla §3 de este documento, en las diez.
- «Persistir procedimiento, tramitación y peso del precio», «Aprobar un acceso
  es editar variables de entorno a mano», «HistGradientBoosting revienta»,
  «Migrar las llamadas al cliente tipado» y «Vigilar el crecimiento de
  `predicciones_baja`» están en Cerrados o en el archivo, y no en P1/P2/P3.
- Ningún stream de Ola 1 que cite una decisión arranca antes de esta fecha.

### O0.6 — La superficie no promete lo que el backend no hace

**Qué.** Seis correcciones pequeñas que convierten promesas rotas en contrato.

**Ficheros.** `api/routes/search.py`, `api/routes/licitaciones.py`,
`api/routes/models.py`, `api/routes/security.py`, `api/routes/me.py`,
`api/routes/webhooks.py`, `api/routes/analytics.py`, `api/scopes.py`,
`scripts/check_openapi_contract.py`, `llm/client.py`, `llm/providers/`,
`web/src/app/(dashboard)/investigador/`, `shared/dto.py`.
**Esfuerzo / gate.** M en total · D15 y D19; la RFC de D19 es **[§6]**
contrato.

**Aceptación.**

a) *Búsqueda semántica (D15).* Si «servir»: `/search/semantic` usa
`hybrid_search_docs` cuando hay embeddings y el campo `source` de la respuesta
dice `rrf`, `fts` o `like`; `alpha` gobierna el peso de la fusión. Si
«retirar»: el deslizador desaparece y la RFC renombra el endpoint. En ambos
casos, un test afirma que la etiqueta que pinta el Investigador coincide con
`source`, y con `documento_chunks` vacío el endpoint responde `source=fts` sin
error.

b) *Cursor, explain, tech-scores y bulk-get con sesión.* Las cuatro rutas
pasan a `require_any_auth`; los scopes de API key no cambian (`api/scopes.py`).
Test: un cliente con cookie de sesión obtiene 200 en `/licitaciones/cursor`;
`grep -c "require_api_key" api/routes/licitaciones.py` = 0.

c) *Activar modelos y verificar auditoría con sesión de administrador.*
`require_admin` en las dos rutas; una API key sigue necesitando `admin`. Test:
sesión de admin → 200; sesión de no admin → 403; key sin scope → 403.

d) *Agujero del ratchet.* `_is_opaque` recorre `items` de `array`; los tres
endpoints del hecho 8 devuelven DTOs. `make check-api-contract` verde con la
comprobación recursiva; `web/src/generated/api.d.ts` sin `unknown[]` en esas
tres operaciones; `make web-codegen` no produce diff después.

e) *Retirada anunciada (D19).* `deprecated=True` en `compare-periods`,
`resumen/sankey`, `resumen/top` y en `GET /licitaciones` por offset; RFC de
retirada con fecha y `status: approved`. Test: OpenAPI marca `deprecated: true`
en las cuatro operaciones.

f) *Modelos de razonamiento.* El cliente envía `chat_template_kwargs` a los
modelos NIM marcados como razonamiento y a ningún otro. Test unitario sobre el
cuerpo de la petición; `make eval-llm` con un modelo de razonamiento devuelve
respuesta no vacía.

### O0.7 — Documentación que el código no desmiente

**Qué.** (a) `docs/database-schema.md` se **genera**: `scripts/gen_schema_doc.py`
aplica `alembic upgrade head` sobre `TEST_DATABASE_URL`, lee
`information_schema` y `pg_indexes` y escribe tablas, columnas, índices y
vistas materializadas agrupadas por familia, con cabecera «generado por». (b)
Los cinco RFC del hecho 25 cambian de `status`; el de relaciones se marca
`obsolete` o se reescribe contra la arquitectura de información actual. (c) La
tabla de características del README deja de dar TED por pendiente.

**Ficheros.** `scripts/gen_schema_doc.py` (nuevo), `docs/database-schema.md`,
`Makefile`, `.github/workflows/ci.yml`, `docs/rfc/*.md`, `docs/rfc/README.md`,
`README.md`, `web/src/app/(publico)/_content/landing.ts`.
**Esfuerzo / gate.** M · **[§6]** `ci.yml`, pre-autorizado en D20.

**Aceptación.**
- `grep -c "SQLite\|FTS5" docs/database-schema.md` = 0 fuera de una nota
  histórica de una línea.
- `make schema-doc` regenera el fichero y `python scripts/gen_schema_doc.py --check`
  corre en el job `static-analysis` de `ci.yml`, como `gen_status --check`.
- Los cinco RFC llevan `status: implemented` o `superseded`;
  `docs/rfc/README.md` escribe el criterio: implementado es que el código
  exista, no que el PR se haya mergeado.
- La cabecera de `_content/landing.ts` deja de advertir de que el README está
  desactualizado, porque ya no lo está.

**Verificación de la ola.** O0.1–O0.4 comprobadas en producción con fecha en
sus ficheros; `make check`, `make check-api-contract` y `make web-test` verdes
tras O0.6; `make check-agent-docs` verde tras O0.7.

---

## 5. Ola 1 — Streams

| Stream | Rama | Migración | Merge |
|---|---|---|---|
| S1 Identidad y equipo | `claude/v2-s1-identidad` | v103 (invitaciones), v104 (proveedor OAuth) | 1º |
| S2 Capacidad y go/no-go | `claude/v2-s2-capacidad` | v105 (NIF), v106 (capacidades) | tras S1 |
| S3 Lotes y bucle del Radar | `claude/v2-s3-lotes` | v107 (`pursuits.lote_id`) | tras S2 (comparten `db/repositories/pursuits.py`) |
| S4 Eventos y salida | `claude/v2-s4-eventos` | v108 (`domain_events.organization_id`, `dispatched_at`), v109 (webhooks por organización) | tras S3 (los eventos de pursuit citan el lote) |
| S5 Cola y worker | `claude/v2-s5-cola` | v110 (`jobs`) | libre; antes que S8 |
| S6 ML: etiquetas | `claude/v2-s6-ml` | no | libre |
| S7 Frontend | `claude/v2-s7-frontend` | no | libre; rebasa sobre S1–S4 al final |
| S8 Documentos | `claude/v2-s8-documentos` | v111 (`documentos.blob_key`, `documento_pages.ocr`) | tras S5 |

**Propiedad exclusiva de ficheros** (un agente por stream, sin solapes):

- `api/routes/auth.py`, `api/routes/pursuits.py` (solo membresías),
  `services/organizations.py`, `db/repositories/organizations.py`,
  `db/users.py`, `shared/identity.py`, `scripts/check_user_key_ratchet.py`: S1.
- `services/go_no_go.py`, `services/analytics/affinity.py`,
  `db/repositories/organization_capabilities.py`,
  `services/pursuit_awards.py`, `web/src/app/(dashboard)/equipo/**`: S2.
- `db/repositories/pursuits.py`, `services/pursuits.py`,
  `services/product_metrics.py`, `db/repositories/product_metrics.py`,
  `web/src/app/(dashboard)/oportunidades/**`, `web/src/components/pursuits/**`: S3.
- `db/events.py`, `shared/events.py`, `scheduler/jobs/event_dispatch.py`,
  `api/routes/webhooks.py`, `db/repositories/webhooks.py`,
  `services/notifications.py`, `services/email_digest.py`,
  `api/routes/watchlist_rules.py`, `services/watchlist_rules.py`,
  `db/repositories/watchlist_rules.py`, `web/src/app/(dashboard)/mi-watchlist/**`,
  `web/src/app/(dashboard)/ops/_components/webhooks-view.tsx`: S4.
- `shared/jobs.py`, `db/repositories/jobs.py`, `scheduler/worker.py`,
  `api/routes/jobs.py`, `scheduler/pipeline_runs.py`, `render.yaml`
  (bloque `worker`), `scripts/check_job_parity.py`: S5.
- `db/repositories/ml_dataset.py`, `scraper/tech_classifier.py`,
  `scraper/ml_training.py`, `services/ml/promotion.py`, `services/ml_eval.py`,
  `tests/fixtures/golden_set*.jsonl`: S6.
- `web/**` salvo lo asignado a S2, S3 y S4: S7.
- `scraper/document_fetcher.py`, `db/repositories/documentos.py`,
  `shared/object_store.py`, `shared/model_artifacts.py`,
  `scheduler/jobs/documentos_embeddings.py`, `.github/workflows/pliegos.yml`: S8.
- `shared/dto.py`: cada stream añade solo sus modelos, en su sección, y rebasa.
- `docs/**` salvo el backlog: el stream que cambia el comportamiento actualiza
  el doc que lo describe en la misma PR; el backlog lo edita cada stream solo
  en sus ítems.

### S1 — Identidad y equipo

**Objetivo:** que una organización pueda incorporar a alguien que aún no tiene
cuenta, que un partner con Microsoft 365 entre con su identidad, y que la
identidad interna deje de ser el email.

1. **Invitaciones pendientes.** `POST /organizations/{id}/members` acepta un
   email sin cuenta: crea la membresía en `invited` con un token firmado
   (`shared/signing`, con `kid`) enviado por email; al registrarse o entrar por
   OAuth con ese email, la membresía pasa a `active`. Reenviar y revocar desde
   `/equipo`. El DTO `OrganizationMemberInvite` ya existe. Esfuerzo M.
   *Aceptación:* invitar a un email sin cuenta → 201 y fila `invited`; login
   posterior con ese email → `active` y la organización aparece en
   `GET /organizations`; el token caduca a los 7 días y es de un solo uso
   (tests); el export GDPR del invitado incluye la invitación y el borrado la
   anonimiza; `/equipo` lista pendientes con reenviar y revocar; un `member` no
   puede invitar (403).
2. **OIDC genérico y Microsoft Entra ID (D17).** El flujo específico de Google
   de `api/routes/auth.py` se abstrae en una tabla de proveedores (`google`,
   `microsoft`) con documento de descubrimiento; PKCE, `nonce` y `state`
   iguales; `access_grants` y la allowlist por dominio aplican a ambos.
   Variables `OAUTH_MICROSOFT_CLIENT_ID`, `OAUTH_MICROSOFT_CLIENT_SECRET` y
   `OAUTH_MICROSOFT_TENANT` en `config/settings.py` y `.env.example`
   (**[§6]**, pre-autorizado). Esfuerzo M.
   *Aceptación:* `GET /auth/oauth/{provider}/authorize` y `/callback` para los
   dos proveedores, con tests de callback sobre un documento de descubrimiento
   simulado; `users.oauth_provider` guarda el proveedor; los usuarios Google
   existentes entran igual (test de regresión); la página de login ofrece
   ambos botones y `oauth-login-telemetry` distingue el proveedor sin
   identificar al usuario.
3. **Dominio propio.** Registrar el dominio, apuntarlo a Vercel, y actualizar
   `FRONTEND_URL`, `CORS_ALLOWED_ORIGINS`, `SMOKE_BASE_URL` y el JSON-LD de la
   superficie pública. Esfuerzo S · acción humana.
   *Aceptación:* `/`, `/sitemap-index.xml` y una ficha pública responden en el
   dominio propio con `canonical` y JSON-LD que lo usan; `seo.spec.ts` pasa
   contra el dominio; el subdominio de Vercel redirige con 308.
4. **Ratchet de `user_key` (D18, fase 1).** `scripts/check_user_key_ratchet.py`
   con la lista de los 60 ficheros de hoy, que solo puede encoger; `make
   status` imprime el conteo; `shared/identity.user_key_from_email` queda
   marcada `@deprecated` en su docstring. Esfuerzo S.
   *Aceptación:* el script falla ante un fichero nuevo con `user_key`; corre en
   `static-analysis`; `docs/STATUS.md` muestra el bloque.

**Verificación:** `make check`, `make check-api-contract`, `make web-test`,
E2E de login con los dos proveedores en CI (proveedor simulado).
**Riesgo:** medio en S1.2 (toca el login).

### S2 — Organización con capacidad: NIF, solvencia y go/no-go asistido

**Objetivo:** que la ficha del pliego tenga contra qué contrastarse, y que el
cierre de una oportunidad sepa quién ganó.

1. **Identidad fiscal de la organización (D11).** Tabla `organization_nifs`
   (NIF normalizado con `services/normalization.normalize_nif`, razón social,
   principal). Endpoints `GET/PUT /organizations/{id}/nifs` para owner/admin.
   Pestaña «Organización» en `/equipo`. Esfuerzo M · **[§6]** migración,
   pre-autorizada.
   *Aceptación:* `PursuitAdjudicacionDetectada` gana `resultado_sugerido:
   won | lost | null`, calculado por NIF, y la ficha lo propone preseleccionado
   sin cerrar sola (tests: NIF de la organización → `won`; otro NIF → `lost`;
   sin NIFs → `null`); el maestro de empresas enlaza el NIF de la organización
   con su `empresa_id` canónico si existe, para que «contra quién» excluya a la
   propia organización de la lista de competidores (test).
2. **Perfil de capacidad.** Tabla `organization_capabilities` con
   certificaciones (nombre, ámbito `company | team`, vigencia), facturación
   anual por ejercicio (tres últimos), referencias (órgano, importe, año,
   tecnología, expediente si es de la plataforma) y perfiles de equipo (rol,
   años, cantidad). DTOs estrictos, `GET/PUT /organizations/{id}/capabilities`,
   owner/admin escriben, viewer lee. Esfuerzo M · **[§6]** migración.
   *Aceptación:* contrato tipado (cero opacos); el perfil es dato corporativo:
   el export GDPR de un usuario no lo incluye y su borrado no lo toca (test);
   tests de permisos en las tres combinaciones de rol; la UI marca qué
   campos faltan para que el checklist de S2.3 deje de decir «desconocido».
3. **Contraste ficha × capacidad.** `services/go_no_go.py` produce, para
   `certifications`, `economic_solvency`, `technical_solvency` y
   `team_requirements` de `TenderFactSheet`, un veredicto `cumple |
   no_cumple | desconocido` con la evidencia del pliego y el dato de la
   organización. Nunca decide por el usuario. `GET /pursuits/{id}/checklist`;
   la pestaña Decisión de la oportunidad lo muestra y permite marcar a mano.
   Esfuerzo L.
   *Aceptación:* golden `tests/fixtures/golden_go_no_go.jsonl` con diez fichas
   y capacidades sintéticas y el veredicto esperado por familia; ningún
   `cumple` sin `EvidenceRef`; `desconocido` cuando la ficha no tiene el hecho
   o la organización no rellenó el campo; cada evaluación se sella una vez por
   versión de ficha en `pursuit_events` (`checklist_evaluated`); el checklist
   declara `extraction_version` y fecha de la ficha que evaluó.
4. **Afinidad desde la capacidad.** `services/analytics/affinity.py` construye
   el portfolio a partir de las referencias y tecnologías de la organización
   cuando el usuario no tiene perfil personal. Esfuerzo S.
   *Aceptación:* test: organización con referencias y usuario sin perfil →
   afinidad no neutral; `ScoringSignalsHealth` gana `afinidad_origen ∈ {perfil,
   organizacion, ninguno}` (aditivo) y el Radar lo enseña en el desglose.

**Verificación:** `make check`, `make check-api-contract`, E2E que crea una
organización con NIF, abre una oportunidad y ve el resultado sugerido.
**Riesgo:** medio en S2.3 (regla de producto nueva; el golden es la red).

### S3 — Oportunidad por lote y bucle del Radar

**Objetivo:** que se pueda pujar por lo que de verdad se puja, y que el
producto responda si el Radar prioriza bien.

1. **Pursuit por lote (D12).** `pursuits.lote_id` nullable con FK a `lotes`;
   dos índices únicos parciales como en `v65`; `PursuitCreate.lote_id`;
   el tablero agrupa por expediente; `escenarios-precio` y `prediccion-baja`
   aceptan `lote_id`. Esfuerzo M · **[§6]** migración.
   *Aceptación:* crear dos oportunidades del mismo expediente con lotes
   distintos → 201 ambas; el mismo lote dos veces → idempotente; sin lote sigue
   funcionando y las filas existentes no cambian (test de migración); el ICS
   incluye el lote en el título; `GET /pursuits/metrics` cuenta por
   oportunidad y lo dice.
2. **Calidad del Radar.** `services/product_metrics.py` calcula por
   `banda_al_abrir` la precisión `won / (won + lost)` y la tasa de cierre, y
   `GET /pursuits/metrics` gana `radar_quality`; `make product-status` lo
   imprime. Esfuerzo S.
   *Aceptación:* test con fixture de doce oportunidades cerradas; el Radar
   muestra «precisión de la banda Caliente en tu organización: n/N» solo con N
   ≥ 10 y, por debajo, «sin datos suficientes» (ADR-014: sin denominador no se
   pinta); la métrica declara la ventana.
3. **Pesos propuestos, nunca aplicados solos.** A partir de las oportunidades
   cerradas con `desglose` sellado, `/mi-perfil` muestra en la sección de la
   organización una propuesta de ajuste de pesos con su base (n ganadas, n
   perdidas). Esfuerzo S.
   *Aceptación:* con menos de veinte cierres devuelve `insuficiente`; un test
   fija la dirección del ajuste (una dimensión más alta en ganadas que en
   perdidas sube); aplicar la propuesta es un clic explícito y queda en
   `audit_log`.

**Verificación:** `make check`; `make product-status` con `radar_quality`;
E2E que abre dos lotes del mismo expediente.
**Riesgo:** medio en S3.1 (clave única de una tabla viva; `plan` antes de
`apply`).

### S4 — Eventos y salida

**Objetivo:** un solo backbone de eventos, y que el equipo se entere donde
trabaja.

1. **Outbox sobre `domain_events`.** Toda mutación relevante escribe un evento
   en la misma transacción vía `db.events.append_event`: pursuit creada,
   cambio de estado, decisión, asignación, comentario; coincidencia de regla;
   adjudicación detectada de un expediente seguido; renovación que entra en
   ventana; ficha extraída; cambio en expediente seguido. Columnas nuevas
   `organization_id` y `dispatched_at` (**[§6]** migración). Un despachador
   (`scheduler/jobs/event_dispatch.py`, plano `pipeline`, y a demanda en el
   worker de S5) abanica hacia `user_notifications`, `pending_digests`,
   `webhook_deliveries` y `cache_signal`. Esfuerzo L.
   *Aceptación:* catálogo de tipos en `shared/events.py` con test que rechaza
   un tipo fuera del catálogo; crear una oportunidad produce exactamente un
   `pursuit.created` y el reintento con la misma `X-Idempotency-Key` sigue
   siendo uno; el despachador es idempotente por `(event_id, canal)` y un test
   que lo interrumpe a mitad no duplica entregas; las inserciones directas en
   `user_notifications` y `pending_digests` fuera del despachador entran en un
   ratchet con la lista de hoy, que solo encoge; `/metrics` expone
   `domain_events_pending` con alerta si supera 1.000 durante una hora.
2. **Webhooks por organización.** `webhooks.organization_id` y `created_by`;
   `require_organization(write=True)` sustituye a `require_admin`; los tipos
   del catálogo entran en `_VALID_EVENTS` con prefijos (`pursuit.*`,
   `licitacion.*`, `adjudicacion.*`, `renovacion.*`, `ficha.*`). Esfuerzo M ·
   **[§6]** migración.
   *Aceptación:* un `member` crea un webhook en su organización y no ve los
   de otra (test de aislamiento en las dos dimensiones, como en `#271`); la
   firma HMAC y la allowlist SSRF no cambian (tests existentes verdes);
   `GET /webhooks/event-types` lista el catálogo completo; la vista de
   webhooks sale de `/ops` y entra en `/equipo` para owner/admin, quedando en
   `/ops` la vista global.
3. **Plantillas Teams y Slack (D13).** `webhooks.formato ∈ {json,
   slack_blocks, teams_adaptive_card}` con un renderer por evento y una página
   de ayuda con capturas. Esfuerzo M.
   *Aceptación:* fixtures de payload por formato validadas contra el esquema
   JSON de Adaptive Cards 1.5 y contra la forma de Block Kit (esquemas en
   `tests/fixtures/`); un evento sin plantilla específica cae a `json`; el
   `ping` envía la plantilla elegida.
4. **Reglas más ricas.** `WatchlistRuleBody` gana `tecnologia`, `organo`
   (normalizado con `services/dedupe.normalize_organo`), `procedimiento`,
   `tipo_contrato`, `banda_min` y `plazo_min_dias`; `preview` y `matches` los
   aplican en SQL. Esfuerzo M · **[§6]** migración aditiva.
   *Aceptación:* test de paridad: `preview` y `matches` devuelven el mismo
   `total` para la misma regla; `banda_min` usa el mismo universo puntuable
   que el Radar (`AggregateRepository.scoring_candidates`); `/mi-watchlist`
   expone los campos con contrato tipado; las reglas existentes no cambian de
   resultado (test de regresión sobre fixture).
5. **Alertas de cambio en expedientes seguidos.** Tras el upsert, por cada fila
   nueva de `licitaciones_history` cuyo `id_externo` esté en `watchlist_items`
   o en una oportunidad abierta de alguna organización, evento
   `licitacion.cambiada` con `changed_fields` y valores anterior y nuevo.
   Esfuerzo M.
   *Aceptación:* cambio de `fecha_limite` en un expediente seguido →
   notificación in-app al seguidor con campo y valores; cambio en un expediente
   no seguido → ningún evento; una re-ingesta sin cambio real (`values_equal`)
   → ningún evento; el productor corre en el cierre y usa el cursor de
   `contract_events` para no releer el historial entero.
6. **Asignaciones y comentarios por email.** `pursuit.assigned` y
   `pursuit.commented` llegan por email según una preferencia por usuario y
   tipo (`immediate | daily | off`). Esfuerzo S.
   *Aceptación:* `immediate` sale en la siguiente pasada del despachador y
   `daily` se agrupa en el digest (tests); `off` no escribe en
   `pending_digests`; quien se asigna a sí mismo no recibe email.

**Verificación:** `make check`; `make fuzz-api` sin 5xx en las rutas nuevas;
E2E que crea un webhook de organización y recibe el `ping`.
**Riesgo:** medio en S4.1 (toca el camino de escritura de pursuits y reglas;
el ratchet de productores es la red).

### S5 — Cola de trabajo y worker (D14)

**Objetivo:** que un despliegue no mate el trabajo de un usuario, y que la
API no pague en su threadpool lo que puede esperar.

1. **Tabla `jobs`** (`id`, `tipo`, `payload_json`, `organization_id`,
   `estado`, `intentos`, `run_after`, `locked_by`, `locked_at`,
   `resultado_json`, `error_detail`), reclamada con `SELECT … FOR UPDATE SKIP
   LOCKED`; `shared/jobs.py` con `enqueue`, `claim`, `ack` y `fail`;
   `job_locks` (`v34`) se retira si la cola lo cubre. Esfuerzo M · **[§6]**
   migración.
   *Aceptación:* dos consumidores concurrentes sobre cien jobs los procesan
   exactamente una vez (test con hilos); un job que lanza excepción reintenta
   con backoff y acaba en `failed` con `error_detail`; un `locked_at` caducado
   vuelve a `pending` (test); todo el SQL vive en `db/repositories/jobs.py`.
2. **Los trabajos a demanda salen de la API.** `ficha-pliego/extract-async`,
   `resumen` sin caché, `exports/download?format=pdf` por encima de un umbral
   de filas y los embeddings de un expediente abierto por un usuario encolan y
   devuelven 202 con `job_id`; `GET /jobs/{id}` tipado y con ámbito de
   organización. `BackgroundTasks` queda solo para efectos triviales
   (`last_used`, emails). Esfuerzo M.
   *Aceptación:* `grep -c "BackgroundTasks" api/routes/licitaciones.py` = 0;
   el 202 responde en menos de 200 ms sin tocar el LLM (test con proveedor
   simulado); `GET /jobs/{id}` de otra organización → 404; el estado de la
   ficha (`ficha-pliego/estado`) lee la cola.
3. **Worker en Render.** `APP_PROFILE=worker` y `scheduler/worker.py`
   consumen la cola; `render.yaml` declara el servicio (**[§6]**,
   pre-autorizado; exige O0.2 cerrado). Actions sigue siendo el único plano de
   cron (ADR-012): los pasos programados pueden encolar y el cierre de
   `scrape-daily` consume su propia cola dentro del job. Esfuerzo M.
   *Aceptación:* `make job-parity` verde con el plano `worker` declarado para
   los tipos a demanda; un despliegue en mitad de una extracción no la pierde
   (el job vuelve a `pending` y otro worker lo termina; test de integración con
   dos procesos); `/health/ready` del worker existe y Render lo usa.
4. **Cierre post-ingesta por pasos independientes.** Cada paso de
   `CANONICAL_STEPS` se encola con dependencias explícitas; un bloqueante que
   falla no impide los que no dependen de él. Esfuerzo M; puede pasar a Ola 2
   si S5.1–S5.3 se alargan.
   *Aceptación:* test con `kpi_precompute` fallando → `watchlist_notify` corre
   igual; el resumen del cierre lista `skipped_por_dependencia` aparte de
   `advisory_failed`; el orden de `CANONICAL_STEPS` sigue siendo la única
   fuente y el test que exige un tier por paso sigue verde.

**Verificación:** `make check`; `make job-parity`; un run de `scrape-daily`
con la cola vacía termina en el mismo tiempo que hoy (±10 %).
**Riesgo:** medio en S5.3 (servicio nuevo en producción).

### S6 — ML: etiquetas antes que modelos

**Objetivo:** que cada modelo entrene sobre una población que se parezca a la
que puntúa, con etiquetas que no sean su propia salida.

1. **Población de entrenamiento acotada.** `db/repositories/ml_dataset.py`
   limita el dataset del clasificador SAP al universo observado
   (`universo_tecnologico_sql`) o excluye las fuentes sin `tecnologia`, según
   el diagnóstico del ítem P2 del backlog; el registro guarda
   `train_population`. Esfuerzo M.
   *Aceptación:* `validate_training_data` pasa; `train-model.yml` produce una
   versión con `recall_no_keyword` informado; la proporción del corpus con
   `ml_proba > 0.7` baja de la mitad y queda medida por
   `scripts/audit_domain_truth.py` con umbral.
2. **Etiquetas no circulares para tecnología.** `train_from_db` lee
   `tecnologia_humana` y `tecnologia_llm` con el SQL en `db/`; el aviso
   `tech_classifier.circular_labels` desaparece cuando hay etiquetas no
   circulares suficientes. Esfuerzo S.
   *Aceptación:* test con fixture: con etiquetas humanas presentes no se emite
   el aviso; el registro guarda `label_sources` con el conteo por origen;
   `train-tech.yml` en verde con ese registro.
3. **Golden set por active learning.** Sesiones de etiquetado sobre la cola de
   `feedback/queue` hasta 300 ejemplos (backlog P1). Acción humana con
   acompañamiento. Esfuerzo L (calendario, no código).
   *Aceptación:* `tests/fixtures/golden_set.jsonl` con al menos 300 filas, cada
   una con `source` y fecha; la desviación del umbral medida por
   `services/ml_eval.py` baja de 0,03; el gate de promoción sigue bloqueando
   por `recall_no_keyword`.
4. **Criterio de promoción escrito para baja v2 y retención v1.**
   `services/ml/promotion.py` gana `min_improvement_over_fold_dispersion` y
   retención obtiene un baseline (prevalencia). Esfuerzo S.
   *Aceptación:* la decisión de promoción tiene test; una versión que no supere
   el criterio queda registrada con `promotion_reason`; el runbook
   `model-rollback.md` cita el criterio.
5. **Predicción por lote.** `GET /licitaciones/{id}/prediccion-baja?lote_id=`
   sirve las filas por lote que `predicciones_baja` ya guarda (depende de
   S3.1). Esfuerzo S.
   *Aceptación:* un expediente con tres lotes devuelve tres predicciones o
   `insuficiente` por lote; sin `lote_id` devuelve la del expediente como hoy.

**Verificación:** `make check`; `train-model.yml` y `train-tech.yml` verdes
con registro de población y etiquetas.
**Riesgo:** bajo; S6.1 cambia lo que sirve el clasificador y va con medición
antes y después.

### S7 — Frontend

**Objetivo:** cerrar lo que el plan de septiembre dejó a medias y quitar las
tres deudas que hoy hacen frágil cualquier pantalla nueva.

1. **S5.1, S5.2 y S5.9 del plan anterior**, con sus criterios tal cual
   (prefetch en servidor con hidratación, páginas monolito partidas en
   `_hooks/` y `_components/` con `max-lines` a 300, y el grupo de rutas
   `(privado)` con `Providers` y `Toaster` montados una vez). La allowlist
   inicial de `max-lines` son los doce ficheros de §1, que solo encoge.
   Esfuerzo L.
   *Aceptación:* las de esos tres ítems; además, `max-lines` corre en
   `make web-lint` y la lista está en `eslint.config`.
2. **Formularios con esquema.** `zod` y `react-hook-form` (**[§6]** deps,
   pre-autorizado) para los seis formularios con validación: login, reglas,
   perfil, equipo, oportunidad y webhooks. Esfuerzo M.
   *Aceptación:* cada esquema deriva sus claves de los tipos generados de
   OpenAPI y un test compara las claves del esquema con el DTO generado (sin
   duplicar la forma a mano); errores por campo con `aria-describedby`;
   `accessibility.spec.ts` verde en las seis pantallas.
3. **Feature flags: leer o borrar.** Hook `useFeatureFlag(name)` sobre
   `GET /feature-flags` y las dos vistas `experimental` de Mercado pasan a
   depender de un flag; si el mantenedor prefiere borrar, RFC de retirada de
   los endpoints. Esfuerzo S.
   *Aceptación:* `grep -rl useFeatureFlag web/src/app` encuentra al menos dos
   ficheros fuera de `ops/`; sin API de flags la vista experimental sigue
   visible y marcada (fail-open, test); el catálogo de telemetría gana el
   evento de vista experimental abierta.
4. **Inspectores desde `md`.** Los inspectores de Radar y Detalle se abren
   como `Sheet` entre `md` y `xl`. Esfuerzo S.
   *Aceptación:* `responsive.spec.ts` a 768×1024 abre el inspector y lee la
   ficha; a 375 se conserva el modo tarjeta; la nota de `radar/page.tsx:801-808`
   desaparece.

**Verificación:** `make web-lint`, `make web-typecheck`, `make web-test`,
`make check-frontend-invariants`, E2E en CI.
**Riesgo:** medio en S7.1 (routing y datos iniciales), como ya dijo el plan
anterior.

### S8 — Documentos: más formatos, OCR y binario

**Objetivo:** que la ficha del pliego cubra los pliegos que existen, no solo
los PDF con texto.

1. **Almacén de objetos para binarios.** `shared/object_store.py` sobre un
   bucket S3-compatible (Supabase Storage o Cloudflare R2), clave
   `documentos/{source_hash}`, columna `documentos.blob_key`; la extracción se
   reprocesa desde el bucket sin volver a PLACSP. Variables en `.env.example`
   (**[§6]**, pre-autorizado); dependencia `boto3`, ya opcional en
   `config/secrets.py`. Esfuerzo M · **[§6]** migración.
   *Aceptación:* implementación de sistema de ficheros para tests; la
   re-extracción con la fuente caída (simulada) termina en `extracted` leyendo
   el bucket; `retention_cleanup` purga binarios de expedientes cerrados hace
   más de 24 meses y lo cuenta; el tamaño del bucket se expone en
   `/analytics/quality`.
2. **DOCX, ODT y ZIP.** `document_fetcher` acepta los content-types de
   Office Open XML, OpenDocument y `application/zip` (expande y procesa los
   PDF y DOCX internos con límite de entradas y de tamaño). Dependencias
   `python-docx` y `odfpy` (**[§6]**, pre-autorizado). Esfuerzo M.
   *Aceptación:* fixtures de cada formato con texto por página lógica y
   offsets (para DOCX, párrafos agrupados; documentado en el módulo);
   `documentos.status` distingue `unsupported` con el content-type;
   `/analytics/quality` expone `documentos_por_formato`.
3. **OCR para escaneados.** `ocrmypdf` en el runner de `pliegos.yml`, con
   `MAX_DOCUMENT_PAGES` como tope y marca `ocr = true` en `documento_pages`;
   `EvidenceRef` gana `ocr: bool` (aditivo). Esfuerzo M · **[§6]** workflow,
   pre-autorizado.
   *Aceptación:* un fixture escaneado produce texto y la ficha lo cita con
   `ocr = true`; el coste por página se mide en el primer run nocturno y se
   anota en `docs/sli-slo.md`; un PDF con texto no pasa por OCR (test).
4. **Artefactos de modelo en el mismo bucket.** `shared/model_artifacts.py`
   resuelve primero el bucket y después la Release de GitHub; sha256 igual.
   Esfuerzo S.
   *Aceptación:* `resolve_active_artifact` funciona sin token de GitHub (test
   de fallback); activar una versión desde la API cambia `model_version` en
   `/explain`, como ya exige S3.2 del plan anterior.

**Verificación:** `make check`; `pliegos.yml` en verde con el desglose por
formato en su resumen.
**Riesgo:** medio en S8.3 (coste de OCR; el tope de páginas lo acota).

---

## 6. Ola 2 — Lo que depende de una decisión o de una migración grande

### T1 — Seguimiento unificado (depende de S4)

**Qué.** Tabla `follows(id, organization_id, user_id, target_type ∈
{licitacion, lote, empresa, organo, cpv}, target_id, kind ∈ {seguir,
descartar}, visibility, channels_json, created_at)`; backfill desde
`watchlist_items`, `watchlist_empresas` y `radar_dismissals`; lectura dual;
`GET/POST/DELETE /follows`; las reglas siguen en `watchlist_rules` y se
enlazan por `target_type = regla` solo en la UI. Retirada de los nueve
endpoints antiguos por **RFC**. Esfuerzo L · **[§6]** migración y RFC.

**Aceptación.**
- Un script de paridad reproduce, para cada usuario, favoritos, empresas y
  descartes desde `follows` con cero diferencias, ejecutado en producción
  antes de retirar la lectura antigua.
- Un solo control «Seguir» en Radar, Detalle, Empresas y Órganos, con el mismo
  componente.
- `make check-api-contract` verde; la RFC de retirada lleva fecha; el ratchet
  de productores de S4.1 no crece.

### T2 — Núcleo tipado (backlog P2, ampliado)

**Qué.** Columnas sombra `fecha_publicacion_ts timestamptz`,
`fecha_limite_ts timestamptz` e `importe_num numeric(14,2)` en
`licitaciones`, rellenadas por el upsert y por backfill; lectura dual en los
fragmentos de `db/sql_fragments.py`; índices `CONCURRENTLY` en revisión
aparte; ventana de lock para el backfill. Esfuerzo L · **[§6]** migración con
ventana.

**Aceptación.**
- `shared/numeric.values_equal` deja de necesitarse para `importe`: un test
  de round-trip exacto pasa contra Postgres.
- `scripts/audit_domain_truth.py` cuenta cero fechas no ISO.
- `EXPLAIN` de las cinco consultas calientes (listado, cursor, scoring,
  overview, pública) sin cast en tiempo de ejecución sobre esas columnas.
- El delta de `make audit-truth-check` antes y después es cero: cambia el tipo,
  no el dato.

### T3 — Tecnología: una sola verdad

**Qué.** `licitacion_tecnologia_score` (`v30`) es el origen;
`licitaciones.tecnologia`, `ml_tecnologias` y `ml_tech_principal` se derivan
(vista o trigger) y dejan de escribirse desde conectores y ML;
`universo_tecnologico_sql` lee la tabla de scores con la precedencia de
ADR-026. Esfuerzo L · **[§6]** migración y reconstrucción de la vista
materializada (ADR-026 §A).

**Aceptación.**
- El test de literales de `tests/test_dedup_guardrail.py` gana una categoría:
  ningún `UPDATE licitaciones SET tecnologia|ml_tecnologias|ml_tech_principal`
  fuera de `db/`.
- `tech_signal_merge` deja de reparar: cero reparaciones en siete días de
  cierre, medido en `ops_events`, y después se retira de `CANONICAL_STEPS`.
- `make audit-truth-check` antes y después con delta anotado.

### T4 — `user_key` → `user_id`, fase 2 (D18)

**Qué.** Columna `user_id` en las tablas que aún no la tienen; backfill por
email; lectura dual; `user_key` deja de escribirse; el GDPR anonimiza por id.
Esfuerzo L · **[§6]** migración.

**Aceptación.**
- El ratchet de S1.4 en cero y `shared/identity.user_key_from_email` sin
  llamadas de producción.
- Un test de cambio de email conserva favoritos, reglas, vistas, descartes,
  notificaciones y oportunidades.
- `make status` deja de imprimir el bloque de `user_key`.

### T5 — Pre-radar y calendario de compra

**Qué.** Vista «Próximas» en el Radar con los estados `PRE` y `CPM` (ya
normalizados por `v91`) y los avisos `pin-*` de TED; estacionalidad por
órgano en `services/analytics/forecast_svc.py` (publicaciones por mes de los
últimos 36 meses); *spike* documentado sobre los planes anuales de
contratación de PLACSP con resultado go/no-go. Esfuerzo M.

**Aceptación.**
- La bandeja «Próximas» lista solo `PRE | CPM` abiertos, con la fecha prevista
  cuando existe y «sin fecha» cuando no.
- La estacionalidad declara `n` meses y no se pinta con menos de doce (ADR-014).
- El spike de planes anuales termina en un doc de `docs/plans/` con muestra,
  formato encontrado y decisión.

### T6 — Informes programados (depende de S4 y S5)

**Qué.** Informe semanal del pipeline por organización (oportunidades por
estado, vencimientos a catorce días, ganadas y perdidas, señales calientes
nuevas) como email HTML con PDF adjunto (`reportlab` ya está en dependencias);
preferencia por organización (día, hora, destinatarios); lo genera el worker
desde el despachador. Esfuerzo M.

**Aceptación.**
- Test de render con fixture; el informe declara universo, ventana y fecha del
  dato (ADR-014).
- Opt-out por usuario; sin seguimiento de aperturas (privacidad, misma regla
  que `lib/analytics.ts`).
- Un informe de una organización sin oportunidades no se envía y lo dice en
  `ops_events`.

### T7 — Cobertura declarada (D16)

**Qué.** `/cobertura` lista las fuentes con estado `activa | opcional | fuera
de alcance` leído de `REGISTERED_SOURCES`, más la lista estática de lo que
queda fuera con fecha: contratos menores, BOE, portales autonómicos no
integrados. Esfuerzo S.

**Aceptación.**
- La página no muestra ninguna cifra de cuota ni suma feeds regionales como
  censo (regla de `docs/regional-source-coverage.md`).
- `seo.spec.ts` cubre la página; el copy pasa `lib/legal-placeholder.ts`.

---

## 7. Métricas de cierre del plan

Se consideran cumplidas cuando el comando indicado las reproduce; no se
anotan cifras a mano en este fichero.

| Métrica | Hoy (2026-09-05) | Objetivo | Cómo medir |
|---|---|---|---|
| Revisiones sin aplicar en producción | 5 (`v98`–`v102`, según el plan anterior §8) | 0 | `GET /health/ready` → `schema: ok` |
| Caminos de despliegue por push a `master` | 2 | 1 | dashboard de Render, siete días |
| Reglas de Prometheus sin receptor | 9 | 0 | `alerting:` + `Watchdog` recibido |
| Decisiones pendientes sin fecha | 9 heredadas + 10 nuevas | 0 | tablas §3 de los dos planes |
| Rutas que la web necesita y solo aceptan API key | 4 (+2 solo `admin` por key) | 0 | grep `require_api_key` en `api/routes/licitaciones.py`; tests de O0.6 |
| Operaciones publicadas que generan `unknown[]` | 3 | 0 | `check_openapi_contract` recursivo |
| Controles de UI sin efecto en el backend | 1 (`alpha`) | 0 | test de `source` en O0.6a |
| Tipos de evento de webhook | 4 | catálogo completo (≥ 12) | `GET /webhooks/event-types` |
| Productores de notificación fuera del despachador | por medir en S4.1 | 0 | ratchet de S4.1 |
| Trabajos pesados en `BackgroundTasks` de la API | 1 | 0 | grep en `api/routes/` |
| Ficheros con `user_key` | 60 | ratchet que solo baja; 0 tras T4 | `make status` |
| Primitivas de seguimiento | 6 tablas / 22 endpoints | 1 tabla / 3 endpoints, más reglas | `git ls-files`, OpenAPI |
| Ficheros de `web/src/app` con más de 300 líneas | 12 | 0 | `max-lines` en `make web-lint` |
| Golden set SAP | 27 | ≥ 300 | `wc -l tests/fixtures/golden_set.jsonl` |
| Formatos de documento soportados | 2 | 5 más OCR | `_SUPPORTED_CONTENT_TYPES` |
| Docs con hechos que el código desmiente | schema doc + 5 RFC + 5 ítems del backlog | 0 | O0.5 y O0.7 |
| Organizaciones con NIF y capacidad rellenada | 0 (no existe) | todas las que abren oportunidades | `make product-status` |
| Precisión de la banda «Caliente» medible | no | sí, con n ≥ 10 | `GET /pursuits/metrics` |
| Proveedores OAuth | 1 | 2 | `GET /auth/oauth/{provider}/authorize` |

## 8. Lo que NO se hace

- **Backup y restore drill.** Fuera por decisión del mantenedor; no se citan
  en ningún ítem.
- **Cortes analíticos ni espacios de consola nuevos.** Mercado y Competencia
  quedan como están; tres endpoints de analítica salen, no entran.
- **Probabilidad de ganar.** Sigue bloqueada por `WinProbabilityGate` hasta que
  S3 acumule cierres con precio suficientes; no se levanta por este plan.
- **Modelos ML nuevos** antes de S6.1–S6.3.
- **i18n del frontend y expansión a la UE.** Fuera hasta que exista un cliente
  fuera de España; `shared/i18n.py` no se amplía.
- **Planes, cuotas y facturación.** No hay decisión de venta como SaaS; los
  `api_key_tiers` existentes bastan.
- **WebSockets.** SSE cubre los dos usos que hay; no se añade otro transporte.
- **Integraciones nativas con OAuth de Slack o Teams** (D13 propone plantillas).
- **Reescritura de `aggregates.py` de golpe.** Sigue la regla del backlog:
  extraer por dominio al tocar.
- **Contratos menores y nuevos portales** hasta que D16 diga otra cosa.

## 9. Secuencia y dependencias

1. Ola 0 entera. O0.1, O0.2 y O0.5 son bloqueantes para todo lo demás.
2. S1 y S5 en paralelo (no comparten ficheros); S6 y S7 en paralelo con ellos.
3. S2 tras S1; S3 tras S2; S4 tras S3; S8 tras S5.
4. Ola 2 en el orden T1 → T4 → T2 → T3 (cada uno con `plan` antes de `apply`),
   y T5, T6 y T7 cuando S4 y S5 estén en producción.

Cada stream cierra con `make check`, `make check-api-contract`, los controles
de frontend que le toquen, la verificación de su migración contra Postgres en
CI y la actualización del backlog y de `docs/STATUS.md`. Un ítem sin verificar
no se marca hecho.
