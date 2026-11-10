---
id: ADR-033
title: "Plano de cron dentro del worker de Render"
status: accepted
date: 2026-09-14
deciders: "Daniel Kalitovics"
related:
  - "[[ADR-012-plano-unico-orquestacion]]"
  - "[[ADR-028-cola-de-trabajo-y-worker]]"
  - "[[ADR-019-observabilidad-desplegada]]"
tags: [adr]
---

# ADR-033 — Plano de cron dentro del worker de Render

- **Estado:** aceptado, **enmendado el 2026-10-10** (ver [Enmienda](#enmienda-2026-10-10-lo-que-el-worker-no-hacía-igual-que-actions))
  y el **2026-11-09**: el plano puede correr como proceso hijo de la API (ver
  [Enmienda](#enmienda-2026-11-09-el-plano-como-proceso-hijo-de-la-api)).
  **Sin efecto en producción desde el 2026-10-19:** el servicio
  `tenderflow-worker` se creó el 2026-10-10 con `SCHEDULER_PLANE=worker`, pero
  en el plan `free` de Render, que lo hibernaba a los ~15 min; su plano de cron
  solo corría tras cada deploy y su intervalo de 4 h no se disparó nunca. Las
  pasadas reales las siguió haciendo Actions (`scrape-daily.yml`, `ml-scoring.yml`),
  que no se llegó a apagar. El servicio se retiró (ver la nota en `render.yaml`
  y la revisión del 2026-10-19 de ADR-028 §G): el plano de cron es de Actions.
  El código (`scheduler/cron_plane.py`) se queda; retomar esta decisión exige un
  worker en un plan que no hiberne y el
  [runbook de cutover](../runbooks/cutover-cron-al-worker.md) desde su paso 1.
- **Fecha:** 2026-09-14
- **Extiende:** [ADR-012](ADR-012-plano-unico-orquestacion.md) — no lo deroga.
  La regla «un solo plano dueño por entorno» sigue vigente; lo que cambia es
  que `SCHEDULER_PLANE` admite un tercer valor.
- **Relacionado:** [ADR-028](ADR-028-cola-de-trabajo-y-worker.md) (el worker que
  aloja el plano), [ADR-019](ADR-019-observabilidad-desplegada.md) (dónde queda
  el registro de ejecuciones cuando se apaga Actions)
- **Cierra:** D43 del [plan de salida al mercado](../plans/2026-09-plan-salida-al-mercado.md)

---

## Contexto

ADR-012 resolvió el problema de 2026-06 —dos planos de orquestación
descoordinados contra la misma base de datos— nombrando un dueño por entorno:
`actions` en producción, `docker` en el stack local. Funcionó: los jobs
`plane="actions"` del registry se disparan desde workflows programados y
`scripts/check_job_parity.py` verifica en CI que cada uno tiene su `python -m`
en un workflow con `cron:`.

Lo que ADR-012 no podía resolver es **dónde** corre ese plano. Al preparar la
salida al mercado aparecen tres consecuencias de tenerlo en GitHub Actions, y
ninguna se arregla con más workflows:

1. **El dato personal sale de la región.** Los digests, las notificaciones y la
   retención tratan datos de usuarios. En Actions ese tratamiento ocurre en
   infraestructura de GitHub en EE. UU. Es un subencargado más que declarar y,
   de la lista de [`docs/legal/subencargados.md`](../legal/subencargados.md),
   el único que no está en la región del dato. Para un cliente B2B que pregunta
   dónde se procesa, la respuesta honesta hoy tiene un asterisco.

2. **El cron programado se apaga solo, y en silencio.** GitHub retrasa y salta
   los `schedule:` bajo carga, y **desactiva** los workflows programados de un
   repositorio sin actividad durante 60 días. La forma del fallo es la misma
   que ADR-012 vino a terminar —un job que nadie ejecuta— solo que del lado de
   la plataforma, donde `check_job_parity.py` no llega: el checker verifica que
   el workflow *existe*, no que GitHub lo esté disparando.

3. **CI tiene las llaves de producción.** Para que Actions ejecute el cron hay
   que darle `DATABASE_URL` con permiso de escritura. Cualquier workflow del
   repositorio —y cualquier action de terceros que alguien añada mañana— corre
   al lado de ese secreto. Es el radio de explosión más grande que tiene el
   proyecto y no lo pide ninguna funcionalidad.

Mientras tanto ya existe un proceso que no tiene ninguno de los tres problemas:
el worker de [ADR-028](ADR-028-cola-de-trabajo-y-worker.md) (`APP_PROFILE=worker`).
Vive en `frankfurt`, la misma región que la base de datos; ya tiene las
credenciales porque consume la cola; y Render vigila su arranque con un
`healthCheckPath`. Lo único que no hace es mirar el reloj.

## Decisión

**El worker puede asumir el plano de cron.** `SCHEDULER_PLANE` pasa a admitir
tres valores: `actions` (el de hoy), `docker` (Compose local) y `worker`. Sigue
habiendo **un** plano activo por entorno.

### 1. Un hilo más en el proceso que ya existe

`scheduler/cron_plane.py` expone `CronPlane`, que el lifespan de `api/app.py`
arranca en un hilo daemon cuando `APP_PROFILE=worker` **y**
`SCHEDULER_PLANE=worker`. Sin la segunda condición devuelve `None` y el worker
sigue siendo exactamente lo que era. No se crea un servicio nuevo en Render: el
coste marginal del plano es un hilo dormido.

### 2. Asume exactamente los jobs `plane="actions"`

Ni uno más. Los otros tres planos del registry se quedan donde están, y no por
omisión:

| Plano | Quién lo ejecuta | Por qué no lo toma el worker |
|---|---|---|
| `actions` | workflow programado | **Es lo que se migra.** Sustitución 1:1, verificable job a job. |
| `manual` | `workflow_dispatch` | No corre solo **a propósito** (`recent_bulk`, 2026-08). Programarlo aquí desharía esa decisión sin que nadie la revisara. |
| `loop` | Docker Compose | Decisión explícita de ADR-012. |
| `pipeline` | `run_daily_pipeline()` | Ya corre dentro de `daily_atom`. Programarlo además aquí lo ejecutaría dos veces por pasada. |

`tests/test_cron_plane.py` fija la regla contra el registry real, incluida la
comprobación de que el conjunto no se queda vacío: un plano sin trabajo haría
del cutover un no-op silencioso, y el humano apagaría los workflows creyendo
que otro los sustituye.

### 3. La exclusión mutua se sostiene dos veces

* **Declarativa.** `scheduler/loop.py` sigue exigiendo `docker` y el plano del
  worker exige `worker`. Un entorno mal configurado no arranca **ninguno** de
  los dos, que es preferible a arrancar los dos.
* **Operativa.** Cada ejecución toma `cron:<job>` en `db.job_locks` con el
  timeout del job como TTL. Durante la ventana del cutover —los workflows
  todavía existen aunque ya no deban mandar— el segundo corredor encuentra el
  lock tomado y se queda en no-op. Es el mismo primitivo que usa la pipeline
  canónica, no uno nuevo.

Si la tabla de locks no responde, **el job se ejecuta igual** y queda el aviso
`cron_plane_lock_indisponible`. Es la menos mala de las dos opciones: con la
base de datos caída el job va a fallar por su cuenta y se verá, mientras que
tratar el error como «lo tiene otro» apagaría el plano en silencio — que es el
modo de fallo que este ADR existe para terminar.

### 4. Hilos, también para los jobs pesados

`scheduler/loop.py` manda los `heavy=True` a un `ProcessPoolExecutor` porque un
proceso sí se puede matar al vencer el timeout. El plano del worker ejecuta
todo en hilos, a sabiendas: el worker es un `type: web` de Render cuyo
healthcheck tiene que seguir contestando, y un segundo proceso con el
intérprete cargado dobla la memoria residente del contenedor (`plan: starter`).
Un OOM se lleva por delante el healthcheck y con él el servicio entero.

Lo que se pierde es la cancelación de un job colgado. Lo que queda es el
timeout —que se registra y alerta igual— y el guardarraíl de solape, que impide
acumular una segunda ejecución encima. Es el mismo trato que ya tienen los jobs
ligeros del loop de Docker y los handlers de la cola a demanda.

## Consecuencias

**A favor**

- El tratamiento de datos personales programado vuelve a la región del dato.
  `docs/legal/subencargados.md` pierde su asterisco en cuanto el cutover
  ocurra.
- Se acaba la dependencia de que GitHub dispare un cron. El worker corre
  mientras el servicio esté vivo, y que esté vivo ya lo vigila Render.
- Actions deja de necesitar `DATABASE_URL` de producción para el cron. Es un
  secreto menos en CI (queda el del deploy, que es otro asunto y otro ADR).
- Un intervalo se cambia con una variable de entorno en Render, no editando un
  `cron:` y esperando a que GitHub lo recoja.

**En contra, y asumido**

- El worker pasa a tener dos responsabilidades: la cola y el reloj. Un job de
  cron largo compite por el mismo contenedor que los handlers a demanda. El
  techo es el `plan: starter`; si se queda corto, la salida es un segundo
  servicio con `APP_PROFILE=worker` y `SCHEDULER_PLANE=worker` — y entonces
  los locks de `job_locks` dejan de ser una red del cutover para ser la
  exclusión de verdad.
- Un job colgado no se cancela (ver §4).
- El registro histórico de ejecuciones deja de estar en la UI de Actions. Lo
  que queda es lo que ya había: `scheduler_job_total` / `scheduler_job_duration_seconds`
  en Prometheus (ADR-019) y `ops_events`, que son la fuente que miran los
  runbooks de todos modos.

**Lo que este ADR no hace**

- **No apaga los workflows.** Borrar `schedule:` de los workflows programados
  es el último paso del cutover y es una acción humana, después de una ventana
  de observación con los dos planos y los locks decidiendo. El runbook lo
  detalla.
- No toca `plane="manual"` ni la cola a demanda.
- No introduce un scheduler con expresiones cron. Los intervalos siguen siendo
  los del registry (`interval_env`, minutos), que es lo que el código ya sabe
  hacer. Un `cron:` de verdad —«el día 1 a las 03:00»— no lo cubre esto y hoy
  no hay ningún job que lo pida.

---

## Enmienda 2026-10-10: lo que el worker no hacía igual que Actions

Una revisión del cutover antes de ejecutarlo encontró que la «sustitución 1:1»
del §2 no lo era, y que la red de seguridad del §3 no existía. Ninguno de los
fallos habría dado error: todos eran trabajo que dejaba de hacerse, o que se
hacía dos veces, en silencio.

1. **`daily_atom` solo ingería PLACSP.** TED, Galicia, Euskadi, las
   adjudicaciones vigiladas, PSCP y TACRC eran steps de `scrape-daily.yml`, no
   parte del job: apagar el workflow habría apagado seis de las siete fuentes.
   El job ahora reproduce la pasada del workflow paso a paso —ingesta,
   conectores con el presupuesto de su step, cierre y healthcheck— y un test
   compara su lista de conectores con el YAML. Cada conector expone
   `ejecutar()`, que no abre ni cierra la BD: su `main()` cerraba el pool, que
   en el worker es el de la cola.
2. **Los locks no excluían a Actions.** Solo el worker toma `cron:<job>`; los
   workflows no toman ninguno. Con los dos planos encendidos, que es lo que
   pedía el runbook, todo habría corrido dos veces. El §3 «operativo» queda
   acotado a lo que sí hace: excluir a otra instancia del worker. El cutover
   apaga los workflows antes de encender el plano.
3. **Un único timeout de 600 s.** La ingesta tiene 45 min solo para PLACSP y
   el scoring tardó 1.049 s el 2026-09-24: cada pasada habría salido como
   timeout con alerta, y el lock —cuyo TTL era ese mismo timeout— caducaba a
   media pasada. Cada job declara ahora su presupuesto
   (`ScheduledJob.timeout_seconds`, el `timeout-minutes` de su workflow), que
   es también el TTL del lock.
4. **El scoring sin su guard.** El worker llamaba a `run_scoring()` a secas:
   sin la regla de una corrida por día UTC, sin fallar ante un serving
   degradado a baseline y sin verificar las filas escritas. Ahora llama a
   `run_scoring_programado()`, que hace las tres cosas.

Y el §2 cambia: **el worker no asume todos los jobs `plane="actions"`.** Dos se
quedan en Actions, con el motivo en `scheduler/cron_plane.py::SE_QUEDAN_EN_ACTIONS`:

- `ml_retrain_baja` publica el `.pkl` en una Release con `gh release upload`;
  en el worker quedaría en el disco efímero del contenedor, y el calendario en
  memoria lo reentrenaría tras cada reinicio. Puede moverse cuando el artefacto
  viva en el almacén de objetos ([ADR-029](ADR-029-almacen-de-objetos.md)).
- `documentos_embeddings` calcula los embeddings con PyTorch y extrae con
  `ocrmypdf`, y ninguno de los dos está en la imagen del worker. Trata pliegos
  públicos, así que el motivo de residencia del dato personal (Contexto, §1) no
  le aplica.

Siguen siendo `plane="actions"` porque es la verdad, y `check_job_parity.py`
sigue exigiendo su workflow programado.

Por último, el servicio de Render de este ADR **no existe todavía** (verificado
el 2026-09-30) y su plan pasa de `starter` a `standard`: el scoring y la ingesta
corren en el mismo proceso que la cola y el healthcheck, y ninguno de los dos se
ha medido fuera de un runner de Actions.

## Enmienda 2026-11-09: el plano como proceso hijo de la API

El worker dedicado no existe y el dueño no va a pagarlo: `tenderflow-api`
(`standard`, 2 GB, 1 CPU) es el único servicio de cómputo. Medido en el panel
de Render del 2026-11-03 al 2026-11-09, ese servicio usa entre el 10 y el 13 %
de su memoria y menos del 2 % de su CPU. El margen que el §4 daba por
inexistente (`plan: starter`, 512 MB) aquí sobra.

**Decisión.** Con `APP_PROFILE=api` y `SCHEDULER_PLANE=worker`, el lifespan de
la API lanza `python -m scheduler.cron_plane` como **proceso hijo**
(`scheduler/cron_proceso.py`) y lo relanza si muere. El hijo ejecuta el mismo
`CronPlane`, con los mismos jobs, locks y presupuestos. El perfil `worker`
conserva el plano en un hilo, como hasta ahora.

**Por qué un proceso y no el hilo del §1 y el §4.** En el proceso de la API un
hilo no sirve, y no por memoria:

1. **El techo de sentencia.** Con `APP_PROFILE=api` cada conexión lleva
   `statement_timeout` de 30 s, que protege el pool de las peticiones. El
   cierre de la pasada tiene consultas legítimas de 40 a 76 s
   (`Settings._relax_batch_statement_timeout`): se cancelarían a medias y en
   silencio. El hijo arranca con `APP_PROFILE=scraper`, el perfil de los
   workflows, y hereda el techo de batch y su propio pool.
2. **La imagen.** El proceso de la API sigue sin importar lxml ni scikit-learn
   (`tests/test_unit_api_imagen_slim.py`). La imagen sí tiene que llevarlos:
   el servicio se construye con `REQUIREMENTS_FILE=requirements-pipeline.txt`.
3. **El aislamiento.** Un job colgado o un pico del scoring no ocupa los hilos
   ni las conexiones que atienden a los usuarios, y el hijo sí se puede matar.

**Lo que cuesta.**

- Cada despliegue de la API corta la pasada en curso y el hijo nuevo la
  repite al arrancar: el calendario vive en su memoria. No se pierden datos
  (upsert idempotente, cursor por fuente). Al recibir SIGTERM el hijo suelta
  sus locks `cron:<job>` y sale sin esperar al job; si no llega a hacerlo,
  el lock dura hasta su TTL y esa pasada se salta.
- Un hijo que muere por su cuenta también empieza con una ingesta al
  relanzarse. El supervisor dobla la espera en cada caída, de un minuto a
  una hora, para que un fallo permanente no las encadene; no hay más freno
  que ese y el aviso `cron_proceso_caido`.
- El hijo abre su propio pool, de 2 + 2 conexiones, que se suman a las de
  la API contra el mismo pooler.
- `tenderflow-api` pasa a tener las credenciales del pipeline (el token de
  lectura de la Release de modelos, el de PSCP, el SMTP de alertas). El
  [runbook](../runbooks/cutover-cron-al-worker.md) las lista.
- El pico de memoria del scoring junto a la API no está medido: es lo primero
  que hay que mirar en las 48 h de observación.

`ml_retrain_baja` y `documentos_embeddings` siguen en Actions por los motivos
de la enmienda anterior. La exclusión con Actions sigue siendo la del runbook:
los workflows se apagan antes de encender la variable.

### Añadido el 2026-11-10: la cadencia sobrevive a los reinicios, y un plano propio

El cutover se ejecutó el 2026-11-09 a las 23:15 UTC: `scrape-daily.yml` y
`ml-scoring.yml` quedaron deshabilitados y `tenderflow-api` lleva
`SCHEDULER_PLANE=worker`. Dos cosas salieron de verlo correr:

- **La marca de cadencia.** El calendario del plano vive en la memoria del
  hijo, y el hijo se reinicia con cada despliegue de la API: cada reinicio
  repetía la ingesta, y un job diario con horas de offset dependía de que nadie
  desplegara mientras tanto. Antes de ejecutar, el plano toma en `job_locks`
  la marca `cron-hecho:<job>`; si sigue viva, el job no toca y se vuelve a
  preguntar a los diez minutos. La marca se toma con el presupuesto del job
  como TTL y solo se alarga al 95 % del intervalo cuando el job termina bien:
  un proceso que muere a media pasada sin poder devolverla (sin memoria, un
  `kill`) no deja el job parado un intervalo entero. Un job que falla, o que
  un despliegue corta a medias, la devuelve.
- **`plane="render"`.** Para los jobs que solo ejecuta este plano. El primero
  es `domain_truth_audit`, la auditoría diaria que lanzaba `domain-truth.yml`:
  `check_job_parity.py` lo da por cubierto si el plano lo asume, y el workflow
  pierde su `schedule:` en el mismo cambio (queda `workflow_dispatch`). El job
  mide en el proceso del plano, sin la sección (b) de los ZIP mensuales, y deja
  las mediciones en el log `domain_truth_mediciones` en vez de en un artefacto:
  la próxima recalibración de umbrales sale de ahí. `daily_atom` y
  `ml_scoring_baja` siguen declarados `actions` hasta que sus workflows pierdan
  el `schedule:`; hoy están deshabilitados a mano, que el repositorio no ve.

Lo que **no** se mueve todavía, con lo que falta en cada caso:

- `documentos_embeddings` (`pliegos.yml`): la imagen de la API no tiene el OCR
  (`ocrmypdf`, `tesseract`), ni `python-docx` y `odfpy`, y sus embeddings
  dependen de que el build haya descargado el modelo ONNX. Moverlo sin eso
  dejaría de leer escaneados, DOCX y ODT sin que nada fallara.
- `ml_retrain_baja` y el entrenamiento de tecnologías (`ml-entrenar.yml`):
  publican el modelo en una Release de GitHub, que es de donde lo lee quien lo
  sirve. Moverlos pide publicar en el almacén de objetos
  ([ADR-029](ADR-029-almacen-de-objetos.md)) y que ese almacén exista en
  producción.
- `healthcheck.yml` y `smoke.yml` se quedan en Actions a propósito: vigilan la
  API desde fuera, y dentro de ella caerían con ella.
