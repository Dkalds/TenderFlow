# ADR-028 — Cola de trabajo y worker: un plano de cron, un plano de trabajo a demanda

- **Estado:** aceptado
- **Fecha:** 2026-09-06
- **Supersede parcialmente:** [ADR-012](ADR-012-plano-unico-orquestacion.md)
  (su regla «un solo plano de orquestación por entorno» se refería al **cron**;
  este ADR declara que el trabajo *a demanda* es un segundo plano legítimo y
  disjunto, y ADR-012 se lee desde hoy con esa acotación)
- **Relacionado:** [ADR-022](ADR-022-frontera-de-persistencia.md),
  [ADR-027](ADR-027-backbone-de-eventos-outbox.md)
- **Implementa:** S5 de
  [docs/plans/2026-09-plan-arquitectura-v2.md](../plans/2026-09-plan-arquitectura-v2.md)

---

## Contexto

ADR-012 fijó que GitHub Actions y APScheduler nunca corren activos contra la
misma BD, con `SCHEDULER_PLANE` declarando el dueño. Esa regla resolvió el
problema real de dos crons duplicando trabajo, y sigue vigente.

Lo que ADR-012 no cubrió es el trabajo **a demanda**: la extracción de una
ficha que un usuario pide, un export PDF grande, los embeddings de un
expediente que alguien acaba de abrir. Hoy eso vive en `BackgroundTasks` de
FastAPI, con tres consecuencias medibles:

1. **Un despliegue mata el trabajo.** `BackgroundTasks` corre en el proceso de
   la API. Render reinicia, la extracción se pierde y el usuario ve un estado
   que nunca avanza.
2. **La API paga en su threadpool** lo que podría esperar, y el OOM del
   2026-08-02 salió de ahí.
3. **No hay reintento ni traza.** Un fallo es una línea de log.

`job_locks` (`v34`) existe, pero es un mutex de cron, no una cola: no guarda
payload, ni intentos, ni resultado.

---

## Decisión

### A. Dos planos disjuntos, con nombres distintos

| Plano | Qué ejecuta | Dueño | Declarado por |
|---|---|---|---|
| **cron** | Trabajo programado (ingesta diaria, KPIs, retención, despachador de eventos) | GitHub Actions en producción | `SCHEDULER_PLANE` (ADR-012, sin cambios) |
| **worker** | Trabajo a demanda encolado por la API | Servicio Render `APP_PROFILE=worker` | `jobs.tipo` en el registry de `make job-parity` |

Ambos planos comparten BD sin conflicto porque **no comparten tipos de
trabajo**: `make job-parity` falla si un tipo aparece en los dos. Esa es la
lectura acotada de ADR-012 que este ADR fija.

El cierre de `scrape-daily` puede consumir su propia cola dentro del job de
Actions: es el mismo código de worker ejecutado en el plano cron, sobre tipos
que ese cierre encoló. No es un segundo consumidor compitiendo.

### B. La cola es una tabla, no un broker

`jobs(id, tipo, payload_json, organization_id, estado, intentos, run_after,
locked_by, locked_at, resultado_json, error_detail)`, reclamada con
`SELECT ... FOR UPDATE SKIP LOCKED`.

Motivo: Postgres ya está, es transaccional con el resto de la escritura, y un
broker (Redis Streams, SQS) añade un componente que hay que operar, pagar y
vigilar para un volumen que hoy no lo justifica. Si el volumen lo justifica, la
frontera `shared/jobs.py` (`enqueue`, `claim`, `ack`, `fail`) permite cambiar
el motor sin tocar los call-sites. Todo el SQL vive en
`db/repositories/jobs.py` (ADR-022).

### C. `locked_at` caducado vuelve a `pending`

Un worker que muere con un job reclamado no lo pierde: pasado el TTL de lock,
otro worker lo vuelve a tomar. La consecuencia es **at-least-once**: un job
puede ejecutarse dos veces, así que todo handler es idempotente o declara por
qué no puede serlo. No se promete exactly-once.

### D. `BackgroundTasks` queda para efectos triviales

Sellar `last_used`, mandar un email suelto. Nada cuya pérdida el usuario note.
El control es `grep -c "BackgroundTasks"` sobre los routers que encolan.

### E. `job_locks` se retira cuando la cola lo cubre

No antes. Mientras haya un cron que dependa de él, sigue.

### F. Excepción: los streams LLM interactivos siguen en línea (2026-09-18)

S5.2 listaba «`resumen` sin caché» entre lo que se encola. Se decide **no
encolarlo**: `POST /licitaciones/{id}/resumen` —como `POST /ask`— sigue
respondiendo en línea con SSE. Es una excepción acotada a los streams que un
usuario está leyendo mientras se escriben, no una puerta para otros trabajos.

Motivos:

1. **El producto es el streaming.** Un resumen sin caché es la generación de
   hasta 1.500 tokens de salida; en SSE el texto se lee mientras se escribe.
   Con 202 + `job_id` + polling el usuario mira un spinner hasta el último
   token: la misma espera total, entera en vacío. Encolar y además
   retransmitir los tokens desde el worker exigiría un canal worker→API
   (pub/sub o tabla de fragmentos) que hoy no existe y que el volumen no
   justifica (§B).
2. **Lo que ADR-028 protege no se pierde aquí.** Un despliegue que corta el
   stream no deja estado a medias: nada se persiste hasta el final (el caché
   solo se escribe con el texto completo), el cliente ve la desconexión al
   instante y reintenta, y desde el 2026-09-17 la desconexión para el hilo del
   LLM (`_stream_sse`, señal `stop`), así que tampoco se sigue gastando
   presupuesto en una respuesta que nadie lee. Es el caso «nada cuya pérdida el
   usuario no note» de §D, pero con la pérdida visible y reintentable en vez
   de silenciosa.
3. **El coste en el threadpool está acotado.** Timeout global
   (`ASK_LLM_TIMEOUT_SECONDS`) y BudgetGuard antes de abrir el stream (429 sin
   tocar al proveedor), y la parte de BD va por `run_db`.
4. **El caso caro se ataca por otro lado.** El resumen se cachea por firma de
   estado, y la pre-generación nocturna (`RESUMEN_PREGEN_ENABLED`, fase 5 del
   job de pliegos) calienta ese caché para las licitaciones seguidas, de
   banda `Caliente` y publicadas hoy: para ellas la ruta sirve el texto
   cacheado sin proveedor. Encolar habría empeorado el caso frecuente para
   proteger uno que ya es raro.

**Disparador de revisión:** si la API pasa a más de una réplica detrás de un
balanceador que no respete conexiones largas, o si el tiempo medio del
resumen sin caché supera el timeout de la plataforma, la decisión se
reabre — en ese punto el canal worker→API deja de ser un coste sin motivo.

`ficha-pliego/extract-async`, el export PDF grande y los embeddings a demanda
**no** entran en esta excepción: no son streams que alguien esté leyendo.

### G. Revisión 2026-10-01: la API consume la cola mientras no haya worker

**Lo que pasó.** El servicio `tenderflow-worker` está declarado en
`render.yaml`, pero el Blueprint nunca se vinculó (O0.2) y el servicio no
existe: la API de Render lista uno solo, el de la API. Los jobs `ficha_pliego`
se encolaban y nadie los reclamaba —siete `pending` con cero intentos, el más
antiguo del 14 de septiembre— y la pestaña Pliego de una oportunidad decía
«Extrayendo la ficha del pliego…» para siempre. Es el riesgo que este ADR ya
nombraba («un worker parado deja la cola creciendo en silencio»), con un worker
que no llegó a arrancar nunca. A la vez, la imagen de la API no traía
`pybreaker` ni `tenacity`, así que la extracción que sí corría en la API (la
de abrir una oportunidad, en `BackgroundTasks`) moría al importar el fetcher.

**Decisión.** El dueño del plano **worker** pasa a ser «el servicio
`APP_PROFILE=worker` si existe; si no, la propia API»:

1. Con `APP_PROFILE=api` el lifespan arranca el mismo consumidor
   (`scheduler/worker.py`, solo `TIPOS_A_DEMANDA`) cuando
   `config.settings.jobs_consumidor_en_api` lo pide: por defecto en
   `prod`/`staging`, nunca en `dev`/`test`. `JOBS_CONSUMIDOR_EN_API=0` lo apaga
   el día que el worker dedicado esté sano; dos consumidores a la vez no son un
   fallo (`SKIP LOCKED`). El plano de cron **no** se mueve: sigue siendo de
   Actions o del worker (ADR-033), nunca de la API.
2. `tenacity` y `pybreaker` pasan a `requirements-api.in`. `python-docx` y
   `odfpy` no (traen `lxml`): un DOCX que la API descarga se queda `pending`
   para el lote nocturno (`ExtractorAusenteError`), en vez de `unsupported`.
3. Abrir una oportunidad encola el job en vez de usar `BackgroundTasks` (§D).

**Lo que se acepta.** La extracción vuelve a compartir proceso con la API, que
es lo que §A quería evitar; el parseo del PDF va en un proceso `spawn` aparte
en `prod` (`scraper/document_fetcher.py`), así que lo que comparte es sobre todo
la espera al LLM. Lo que **no** vuelve es lo peor de `BackgroundTasks`: el
trabajo sigue siendo una fila con intentos, error y TTL, y un despliegue lo
devuelve a `pending` en vez de perderlo.

**Disparador de revisión:** crear `tenderflow-worker` en Render. En ese momento
`JOBS_CONSUMIDOR_EN_API=0` en la API y este apartado queda como historia.

---

## Consecuencias

**A favor.** Un despliegue deja de perder trabajo. La API responde 202 con
`job_id` en vez de bloquear. Un fallo tiene intentos, `error_detail` y una
consulta que lo encuentra.

**En contra.** Un servicio más que operar y pagar en Render, y una latencia de
polling entre encolar y ejecutar. El coste mensual del servicio se anota en
[docs/COSTES.md](../COSTES.md).

**Riesgo.** Un worker parado deja la cola creciendo en silencio. Lo cubren
`/health/ready` del worker (Render lo usa) y la métrica de pendientes por
tipo, con el mismo criterio que `domain_events_pending` de ADR-027.

**Lo que este ADR no decide.** Qué trabajos concretos se encolan (S5.2) —salvo
la excepción de §F, que dice cuáles **no**—, ni el desglose por pasos del
cierre post-ingesta (S5.4).
