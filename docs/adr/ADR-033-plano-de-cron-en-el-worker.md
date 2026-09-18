# ADR-033 — Plano de cron dentro del worker de Render

- **Estado:** aceptado. **El código está; el cutover no:** mientras
  `SCHEDULER_PLANE` no diga `worker` en el servicio de Render, esta decisión no
  cambia nada en producción (ver el
  [runbook de cutover](../runbooks/cutover-cron-al-worker.md)).
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
