# ADR-027 — Un solo backbone de eventos: outbox sobre `domain_events`

- **Estado:** aceptado
- **Fecha:** 2026-09-06
- **Relacionado:** [ADR-022](ADR-022-frontera-de-persistencia.md),
  [ADR-012](ADR-012-plano-unico-orquestacion.md) (el despachador corre en el
  plano `pipeline` y, a demanda, en el worker de
  [ADR-028](ADR-028-cola-de-trabajo-y-worker.md)),
  [ADR-024](ADR-024-services-biblioteca-no-frontera.md)
- **Implementa:** S4.1 de
  [docs/plans/2026-09-plan-arquitectura-v2.md](../plans/2026-09-plan-arquitectura-v2.md)

---

## Contexto

Hoy conviven tres formas de enterarse de que algo pasó:

1. `db/events.py::append_event` escribe en `domain_events` — una tabla
   inmutable que ya existe desde `baseline002` y que hoy usa sobre todo
   `append_cache_invalidation_event` y los `replay_*`.
2. Varios caminos insertan **directamente** en `user_notifications` y en
   `pending_digests` sin pasar por ningún evento.
3. `db/webhooks.py` dispara HTTP de forma síncrona dentro de la request que
   provocó el cambio.

Las tres consecuencias son las de siempre cuando no hay outbox: una
notificación puede escribirse aunque la transacción que la motivó acabe en
rollback; un canal nuevo (email, webhook, cache-signal) obliga a tocar cada
call-site; y no hay forma de responder «¿qué pasó con la oportunidad 42?» sin
leer cinco tablas.

`domain_events` no tiene `organization_id` —el producto es multi-tenant desde
la migración de tenancy— ni marca de despacho, así que tampoco puede usarse
como outbox tal cual está.

---

## Decisión

### A. `domain_events` es el outbox, y es el único

Toda mutación relevante escribe **un** evento en `domain_events` **dentro de la
misma transacción** que la mutación, vía `db.events.append_event`. Ningún
call-site de producción vuelve a insertar directamente en `user_notifications`,
`pending_digests` ni `webhook_deliveries`.

Columnas nuevas (migración `v108` de v2 S4.1):

| Columna | Tipo | Motivo |
|---|---|---|
| `organization_id` | `INTEGER NULL` | Ámbito del evento. `NULL` = evento de plataforma (invalidación de caché, ingesta). |
| `dispatched_at` | `TEXT NULL` | Marca de abanicado. `NULL` = pendiente. Es la columna que hace de esta tabla un outbox. |

### B. El catálogo de tipos es cerrado y vive en `shared/events.py`

Un tipo fuera del catálogo es un error, no un evento con nombre nuevo. El
catálogo se organiza por prefijo de agregado: `pursuit.*`, `licitacion.*`,
`adjudicacion.*`, `renovacion.*`, `ficha.*`, `regla.*`. Un test rechaza
`append_event` con un tipo no catalogado.

Motivo: los webhooks (`_VALID_EVENTS`) y las reglas de suscripción necesitan
enumerar los tipos, y una enumeración que se deduce por `grep` de literales no
es una enumeración.

### C. El despacho es un paso aparte, idempotente por `(event_id, canal)`

`scheduler/jobs/event_dispatch.py` lee eventos con `dispatched_at IS NULL`,
abanica hacia los canales (`user_notifications`, `pending_digests`,
`webhook_deliveries`, `cache_signal`) y marca `dispatched_at`. La idempotencia
es por par `(event_id, canal)`, no por evento: un despachador interrumpido a
mitad reintenta el canal que faltaba sin duplicar el que ya salió.

El despachador corre en el plano `pipeline` (ADR-012) y, a demanda, dentro del
worker de ADR-028. No corre dentro de la request.

### D. La escritura directa a canales queda congelada por ratchet

Los call-sites que hoy insertan en `user_notifications` y `pending_digests` sin
evento entran en una lista que **solo puede encoger**, igual que el ratchet
TID251 de ADR-022. Un call-site nuevo fuera del despachador falla el control.

### E. La cola de pendientes es observable

`/metrics` expone `domain_events_pending`. Una cola que crece es un
despachador parado, y un despachador parado hoy no se nota hasta que alguien
pregunta por qué no le llegó el email.

---

## Consecuencias

**A favor.** Un canal nuevo se añade en un sitio. Una notificación no puede
sobrevivir al rollback de su causa. `domain_events` responde por historia del
agregado sin cruzar tablas. Los webhooks salen de la request.

**En contra.** La entrega deja de ser síncrona: entre la mutación y la
notificación hay una pasada del despachador. Es un coste aceptado; lo que se
compra es que la notificación exista siempre que la mutación existió.

**Riesgo.** El despachador se convierte en un punto único. Lo cubren
`domain_events_pending` con alerta (§E) y el hecho de que reprocesar es releer
`dispatched_at IS NULL`, no reconstruir estado.

**Lo que este ADR no decide.** El formato de los payloads por canal (S4.3), las
preferencias por usuario y tipo (C2.7 del plan complementario) ni el reintento
de los webhooks (C2.4). Los tres consumen este backbone; ninguno lo redefine.
