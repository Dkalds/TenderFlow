---
tags: [runbook, operacion, scheduler]
---

# Runbook — cutover del cron de GitHub Actions al worker

**Qué hace este runbook:** mueve la ingesta diaria y el scoring de producción
de GitHub Actions al worker de Render, con vuelta atrás en dos clics.
Implementa [ADR-033](../adr/ADR-033-plano-de-cron-en-el-worker.md) con su
enmienda del 2026-10-10.

**Quién lo ejecuta:** una persona con acceso al dashboard de Render y
administración del repositorio en GitHub. **Ningún agente puede hacerlo**: los
pasos 1, 4 y 8 son cambios de configuración en las plataformas, y el 7 toca
workflows.

**Estado (2026-10-10):** no ejecutado. **`tenderflow-worker` no existe en
Render** (verificado por su API el 2026-09-30): el paso 1 lo crea. El código
está en el árbol y es inerte mientras `SCHEDULER_PLANE` no diga `worker`.

---

## Qué se mueve y qué no

| Job | Hoy lo ejecuta | Tras el cutover |
|---|---|---|
| `daily_atom` — PLACSP, los seis conectores, el cierre y el healthcheck | `scrape-daily.yml`, cada 4 h | **worker**, cada 4 h |
| `ml_scoring_baja` — scoring, drift, calibración, purgas | `ml-scoring.yml`, tras cada ingesta, una vez al día UTC | **worker**, una vez al día UTC (mismo guard) |
| `ml_retrain_baja` | `train-predictivos.yml`, mensual | Actions, sin cambios |
| `documentos_embeddings` | `pliegos.yml`, nocturno | Actions, sin cambios |

Los dos que se quedan tienen el motivo escrito en
`scheduler/cron_plane.py::SE_QUEDAN_EN_ACTIONS`: el reentrenamiento publica el
`.pkl` en una Release, que el worker no puede hacer, y los embeddings necesitan
PyTorch y `ocrmypdf`, que no están en su imagen. Tampoco se mueve lo que no es
un job del registry: `healthcheck.yml`, `scrape-bulk.yml`, `migrate.yml`,
`deploy.yml` y el resto siguen en Actions.

### Por qué los dos planos no conviven

La versión anterior de este runbook encendía el worker con los workflows aún
activos y confiaba en los locks `cron:<job>` para decidir quién ejecutaba cada
disparo. **Esa red no existe:** solo el worker toma esos locks, los workflows
no toman ninguno. Con los dos encendidos, todo corre dos veces. Los datos no se
duplican, porque el upsert es idempotente, pero sí la carga contra Supabase y
las llamadas al LLM. Por eso el paso 4 **apaga Actions antes de encender el
worker**. El lock sigue sirviendo para lo suyo: que dos instancias del worker
(o la vieja y la nueva durante un despliegue) no ejecuten la misma pasada.

---

## 0. Antes de empezar

| Comprobación | Cómo | Qué esperar |
|---|---|---|
| El código está en `master` y desplegado en la API | GitHub → PR del cutover mergeado; `deploy.yml` en verde | — |
| Los dos planos se conocen | `ENV=dev python scripts/check_job_parity.py` | exit 0 |
| Qué jobs asume el worker | `ENV=dev python -c "from scheduler.cron_plane import jobs_del_plano; print([j.name for j in jobs_del_plano()])"` | `['daily_atom', 'ml_scoring_baja']` |

La lista de jobs es el contrato del cutover: al terminar, esos dos nombres
aparecen en los logs del worker con su cadencia y en ningún sitio más.

---

## 1. Crear el worker en Render (una sola vez)

`render.yaml` describe el servicio, pero no está vinculado a un Blueprint, así
que se crea a mano. Dashboard → **New → Web Service** → el repositorio, rama
`master`:

| Campo | Valor |
|---|---|
| Name | `tenderflow-worker` |
| Region | Frankfurt (la misma que la API) |
| Language / Runtime | Docker |
| Dockerfile Path | `./docker/Dockerfile.api` |
| Instance Type | **Standard** (2 GB). El motivo está junto al servicio en `render.yaml` |
| Health Check Path | `/api/v1/health/ready` |
| Auto-Deploy | **Off** |

Variables de entorno. Las de la API se copian de `tenderflow-api` →
Environment. Los secrets de GitHub **no se pueden leer** una vez creados, así
que las de alertas se copian de `tenderflow-alertmanager`, que tiene las
mismas:

| Variable | Valor | De dónde sale |
|---|---|---|
| `ENV` | `prod` | — |
| `APP_PROFILE` | `worker` | — |
| `REQUIREMENTS_FILE` | `requirements-pipeline.txt` | — (sin ella la imagen no lleva lxml ni scikit-learn) |
| `DATABASE_URL`, `DATABASE_SSL_ROOT_CERT` | igual que la API | `tenderflow-api` (rol `tenderflow_app`, el mismo que usa Actions) |
| `DB_POOL_SIZE`, `DB_READ_POOL_SIZE` | `2`, `2` | — (presupuesto del pooler, ver `render.yaml`) |
| `REDIS_URL`, `REDIS_PASSWORD` | igual que la API | `tenderflow-api` |
| `NVIDIA_API_KEY` | igual que la API | `tenderflow-api` |
| `AUDIT_HMAC_KEY` | igual que la API | `tenderflow-api` |
| `SENTRY_DSN` | igual que la API (opcional) | `tenderflow-api` |
| `JOBS_LOCK_TTL_SEGUNDOS` | `900` | — |
| `ALERT_EMAIL_TO`, `ALERT_SMTP_USER`, `ALERT_SMTP_PASSWORD` | los de alertas | `tenderflow-alertmanager` |
| `ALERT_MIN_LEVEL` | solo si está definida en Actions | GitHub → Settings → Variables → Actions |
| `GITHUB_TOKEN` | token *fine-grained* sobre este repo, `Contents: read` | GitHub → Settings → Developer settings. El scoring descarga el modelo de la Release `ml-models`; sin token, la llamada va anónima y degrada a baseline. Con `Actions: read and write`, además, el paso semanal de aprendizaje activo puede lanzar `train-model.yml`; sin ese permiso avisa por correo para lanzarlo a mano |
| `PSCP_DATASET_ID`, `TACRC_INDEX_URL` | los de Actions | GitHub → Settings → Variables. Sin ellas la fuente se declara `disabled` |
| `PSCP_APP_TOKEN` | el token de Socrata | La cuenta de datos abiertos de Catalunya (el secret de GitHub no se puede leer) |
| `LLM_TECH_LABELING_ENABLED`, `LLM_TECH_LABELING_MODEL`, `LLM_TECH_LABELING_BATCH`, `LLM_TECH_FEEDBACK_ENABLED` | solo las que estén definidas en Actions | GitHub → Settings → Variables. Si no están, manda el default del código, como en Actions |
| `SCHEDULER_PLANE` | **no la pongas todavía** | Es el paso 4 |

Las cinco últimas filas antes de `SCHEDULER_PLANE` todavía no están declaradas
en `render.yaml`: falta documentarlas en `.env.example`, que requiere OK
explícito (AGENTS.md §6). Se ponen igual desde el dashboard.

Desplegar y comprobar:

1. `curl -fsS https://<host-del-worker>/api/v1/health/ready` → `200`.
2. En los logs: `worker_arrancado` (el consumidor de la cola) y
   `cron_plane_inactivo` (el cron sigue apagado, que es lo correcto).
3. Render → `tenderflow-worker` → **Shell**:
   ```bash
   python -c "import lxml, sklearn, statsmodels; print('dependencias ok')"
   python -m scheduler.healthcheck            # lectura: BD y entorno
   python -m scraper.connectors.galicia       # una fuente ligera e idempotente
   python -c "from observability.alerts import notify; print(notify('error', 'Prueba del worker', body='SMTP ok'))"
   ```
   Tiene que llegarte el correo de la última línea (va como `error` para que
   no lo filtre un `ALERT_MIN_LEVEL` alto). Si no llega, las alertas del cron
   tampoco llegarán.

`deploy.yml` solo dispara el deploy hook de `tenderflow-api`. Mientras no
dispare también el del worker, **cada merge a `master` deja al worker con el
código anterior**: hasta entonces, tras cada despliegue de la API, Render →
`tenderflow-worker` → *Manual Deploy → Deploy latest commit*.

Opcional y aparte: con el worker sano, `JOBS_CONSUMIDOR_EN_API=0` en
`tenderflow-api` saca la cola a demanda del proceso de la API (ADR-028 §G). No
es parte de este cutover.

---

## 2. Elegir la ventana

Un día laborable por la mañana, **no** un viernes ni la víspera de un festivo:
la observación dura 48 h y alguien tiene que estar mirando. El momento exacto,
justo después de que termine una pasada de `scrape-daily` (arrancan a las
hh:23 UTC cada 4 h) y con `ml-scoring` ya terminado.

---

## 3. Comprobar que no hay nada en vuelo

GitHub → Actions → **Scrape PLACSP diario** y **ML scoring predicciones**:
ninguna ejecución `In progress`. Deshabilitar un workflow no cancela la
ejecución que ya está corriendo; si hay una, esperar a que termine.

---

## 4. El cambio (unos cinco minutos, en este orden)

1. **Apagar Actions.** GitHub → Actions → cada uno de estos dos workflows →
   `···` → **Disable workflow**:
   - `Scrape PLACSP diario (ATOM live feed + conectores)` (`scrape-daily.yml`)
   - `ML scoring predicciones` (`ml-scoring.yml`)

   No tocar `pliegos.yml`, `train-predictivos.yml` ni `healthcheck.yml`.
2. **Encender el worker.** Render → `tenderflow-worker` → Environment →
   `SCHEDULER_PLANE = worker` → Save. Render redespliega el servicio.
3. **Verificar en los logs**, en este orden:
   ```
   cron_plane_arrancado    plano=worker  jobs=['daily_atom', 'ml_scoring_baja']
   cron_plane_planificado  intervalos_min={'daily_atom': 240, 'ml_scoring_baja': 240}
   ```
   `daily_atom` arranca en el acto: un `daily_atom_conector_completado` por
   cada conector y al final `daily_atom_pasada_completada` con el estado de
   cada parte. Treinta minutos después, `ml_scoring_guard`.

   Si aparece `cron_plane_inactivo`, la variable no llegó al proceso: revisar
   que se guardó en `tenderflow-worker` y no en `tenderflow-api`.

---

## 5. Observar 48 horas

Una vez por turno:

1. **La pasada corre cada 4 h.** Un `daily_atom_pasada_completada` cada ~4 h,
   con `conectores` en `success` o con un motivo que ya se conocía (PSCP agota
   a veces su presupuesto hacia las 09:00 UTC; ya pasaba en Actions).
2. **Las siete fuentes siguen entrando:**
   ```sql
   SELECT source, status, last_started_at, last_success_at
   FROM source_ingestion_health
   ORDER BY last_success_at DESC NULLS LAST;
   ```
   `last_success_at` avanza en todas las que no estén `disabled`. El
   healthcheck de cada pasada avisa también si una se queda atrás.
3. **El scoring corre una vez al día UTC:** un `ml_scoring_guard` con
   `motivo=primera_del_dia` (o `sin_scoring_previo`) al día, y los demás
   `ya_puntuado_hoy`.
4. **La memoria aguanta.** Render → `tenderflow-worker` → Metrics → Memory.
   Anotá el pico de la pasada de `daily_atom` y el del scoring. Un reinicio del
   servicio durante un job es un OOM: vuelta atrás (paso 8).
5. **Nada se dio por colgado:** ningún `scheduler_loop_job_timeout` ni
   `daily_atom_conector_presupuesto_agotado` nuevo. En Prometheus,
   `scheduler_job_total{status=~"error|timeout"}`, y por conector
   `scheduler_job_total{job=~"daily_atom:.*"}`.
6. **Nadie más corre:** ningún `cron_plane_job_saltado_por_lock`. Si aparece,
   hay una segunda instancia del worker.

Rellená esta tabla al terminar:

| Job | Primera ejecución en el worker | Duración | Pico de memoria | ¿Fallos o timeouts? |
|---|---|---|---|---|
| `daily_atom` | | | | |
| `ml_scoring_baja` | | | | |

*(Sin datos: el cutover no se ha ejecutado.)*

---

## 6. Secretos de Actions: qué se puede retirar

Poco, de momento. `DATABASE_URL` lo siguen leyendo trece workflows (los que no
son de cron: `healthcheck`, `migrate`, `pliegos`, `train-predictivos`,
`scrape-bulk`, los backfills…), `PSCP_APP_TOKEN` lo usa también
`purga-pscp.yml` y `NVIDIA_API_KEY` `pliegos.yml` y `scrape-bulk.yml`.
Compruébalo antes de borrar nada:

```bash
grep -ln "secrets\.<NOMBRE>\b" .github/workflows/*.yml
```

Lo que este cutover sí consigue es lo que motivó el ADR: el procesamiento de
datos personales del cierre (digests, notificaciones, retención) ocurre en
Frankfurt, y la ingesta deja de depender de que GitHub dispare un `schedule:`.
Sacar la credencial de producción de CI exige mover también esos otros
workflows, y es otro trabajo.

---

## 7. Borrar los disparadores de Actions (PR, tras dos semanas)

En un PR aparte y con CI verde:

- `scrape-daily.yml`: quitar el bloque `schedule:`.
- `ml-scoring.yml`: quitar `schedule:` **y** `workflow_run:` (se encadenaba a
  `scrape-daily`).
- Dejar en los dos el `workflow_dispatch:` para poder lanzarlos a mano, y
  volver a habilitarlos en la UI de Actions.

Al quitarlos, `scripts/check_job_parity.py` **empezará a fallar** para esos
dos jobs: su regla es que un job `plane="actions"` viva en un workflow
programado. Ese fallo es correcto, y marca el trabajo de este paso: añadir el
plano `worker` al `Literal` de `scheduler/jobs/_base.py`, marcar con él los dos
jobs, y enseñar al checker que un job `worker` tiene que estar en
`jobs_del_plano()` y no en un workflow programado. `PLANOS_ASUMIDOS` pasa a
incluir `worker`.

Se deja para el final a propósito: mientras exista la vuelta atrás de un clic,
el registry tiene que seguir diciendo la verdad, que es «lo dispara Actions».

---

## 8. Vuelta atrás

En cualquier punto anterior al paso 7, en este orden:

1. Render → `tenderflow-worker` → Environment → `SCHEDULER_PLANE = actions`
   (o borrarla) → Save. Comprobar en los logs: `cron_plane_inactivo`. El
   worker sigue consumiendo la cola.
2. GitHub → Actions → **Enable workflow** en los dos que se deshabilitaron.

No hace falta tocar la base de datos. Los locks `cron:*` caducan con el
presupuesto del job (hasta 2 h en `daily_atom`) y solo los mira el worker. Si
uno quedara tomado por un worker muerto y hubiera que volver a encender el
plano antes:

```bash
python -c "from db.job_locks import force_release; force_release('cron:daily_atom')"
```

Después del paso 7 la vuelta atrás ya no es de un clic: hay que revertir ese PR.

---

## 9. Qué mirar cuando el cron del worker falla

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `cron_plane_inactivo` en el arranque | `SCHEDULER_PLANE` no llegó al proceso | Revisar la variable en `tenderflow-worker` |
| `ModuleNotFoundError: lxml` / `sklearn` | La imagen se construyó sin `REQUIREMENTS_FILE` | Añadirla y redesplegar (es un *build arg*) |
| Ningún log del cron y el worker vivo | El hilo murió, o `APP_PROFILE` no es `worker` | Reiniciar; si se repite es un bug, el bucle traga excepciones por diseño |
| `daily_atom_conector_presupuesto_agotado` | La fuente tardó más que su `timeout-minutes` | Igual que en Actions: el cierre sigue sin ella. Si se repite, mirar la fuente |
| `daily_atom_conector_saltado_por_solape` | El hilo de la pasada anterior de ese conector sigue colgado | Se resuelve cuando termina. Si dura, reiniciar el servicio |
| `ML scoring degradado a baseline` | El worker no pudo descargar el `.pkl` activo | `GITHUB_TOKEN` (paso 1), y que `train-predictivos.yml` lo haya subido |
| Timeouts de pool (`PoolTimeout`) | Dos conexiones de escritura no bastan con un conector colgado | Subir `DB_POOL_SIZE` a `3`, comprobando antes el margen del pooler (nota en `render.yaml`) |
| No llegan correos | Faltan las `ALERT_*` | Paso 1; probar con el `notify` del paso 1.3 |
| `cron_plane_job_saltado_por_lock` continuo | Otro worker activo | Buscar la segunda instancia |
| `cron_plane_lock_indisponible` | La tabla `job_locks` no responde | Es la BD, no el cron: [disaster-recovery.md](disaster-recovery.md) |
| Reinicios del worker durante un job | OOM | Vuelta atrás (paso 8); subir de plan antes de repetir |
