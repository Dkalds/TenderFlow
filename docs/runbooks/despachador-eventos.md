---
tags: [runbook, operacion, eventos, notificaciones]
---

# Runbook — despachador del outbox (`domain_events`)

**Qué es:** el paso `event_dispatch` del cierre de cada pasada
(`scheduler/pipeline_runs.py`, plano `pipeline`, ADR-012) llama a
`scheduler/jobs/event_dispatch.run()`, que reparte los eventos pendientes de
`domain_events` hacia la campana (`user_notifications`), el digest
(`pending_digests`), los webhooks y la señal de caché
([ADR-027](../adr/ADR-027-backbone-de-eventos-outbox.md)). Estuvo escrito y sin
cablear desde S4.1 hasta el 2026-09-19: ningún evento se entregaba.

## Orden dentro de una pasada

1. `emitir_tareas_que_vencen` — `pursuit.task_due` del día (C6.1).
2. `services/avisos_outbox.emitir_avisos` — los productores sin mutación:
   documentos nuevos (F5.1), recursos (F5.2), publicaciones nuevas y
   vencimientos a seis meses de las cuentas objetivo (F1.5). Cada uno con su
   cursor en `ingestion_cursors` (`outbox_documentos_nuevos`,
   `outbox_recursos`, `outbox_cuentas_publicaciones`); la primera pasada
   **fija el cursor en el máximo actual y no emite nada**.
3. `caducar_viejos` — lo pendiente con más de `EVENT_DISPATCH_MAX_AGE_HOURS`
   sale de la cola sin entregarse.
4. `dispatch_pending` — hasta 200 eventos por pasada.

El paso va **después** de `watchlist_notify` (que escribe los eventos de reglas
y de competidores, F3.4) y **antes** de `digests`, así que lo que el
despachador encola en modo `daily` sale en el digest de la misma mañana.

## Decisión sobre la cola acumulada (2026-09-19)

Al cablearlo, la cola traía todo lo escrito desde S4.1. **No se entrega.** Un
«te han asignado» de hace diez días o un webhook que anuncia un plazo ya
vencido es ruido que enseña a ignorar el canal. Lo que supera la antigüedad
máxima se marca `dispatched_at` sin pasar por ningún canal; el evento no se
borra (sigue en `domain_events` para la cronología).

La regla es permanente, no sólo del arranque: un evento atascado —un canal que
falla pasada tras pasada, o el despachador apagado más de dos días— caduca
igual en vez de salir tarde.

## Variables

| Variable | Defecto | Efecto |
|---|---|---|
| `EVENT_DISPATCH_ENABLED` | `1` | `0`/`false`/`off` apaga el paso (queda `skipped` en el resumen del cierre). Los eventos se siguen escribiendo y esperan en la cola. |
| `EVENT_DISPATCH_MAX_AGE_HOURS` | `48` | Antigüedad máxima de entrega. Mínimo 1; un valor ilegible cae al defecto. |

Las dos se leen en cada pasada: cambiarlas no exige desplegar, sólo que el
siguiente cierre las vea (variables del workflow o del entorno del runner).

## Cómo saber qué pasó

- **Log del cierre:** `event_dispatch_done` (procesados, caducados, in_app,
  digest, correos, webhooks, fallidos) y `event_dispatch_caducados` con el
  conteo por tipo. `avisos_outbox_emitidos` para los productores.
- **`ops_events`:** la serie `domain_events_caducados` (valor = cuántos,
  detalle = conteo por tipo). Es la que sobrevive a los runners efímeros de
  Actions:

  ```sql
  SELECT ts, value, detail FROM ops_events
  WHERE event_type = 'domain_events_caducados' ORDER BY ts DESC LIMIT 20;
  ```

- **Cola:** `/metrics` expone `domain_events_pending`; la alerta
  `DomainEventsBacklogHigh` salta con más de 1.000 durante una hora. Con el
  paso cableado y la caducidad a 48 h, una cola alta significa que el paso no
  está corriendo (cierre caído o `EVENT_DISPATCH_ENABLED=0`), no que se esté
  acumulando trabajo.

## Apagar y volver a encender

1. `EVENT_DISPATCH_ENABLED=0` en el entorno del cierre. El paso queda
   `skipped` y no se envía nada.
2. Para encender, quitar la variable. En la primera pasada, lo que lleve más de
   `EVENT_DISPATCH_MAX_AGE_HOURS` en cola caduca sin salir. Si la parada fue
   corta y **sí** se quiere entregar lo acumulado, subir temporalmente
   `EVENT_DISPATCH_MAX_AGE_HOURS` para esa pasada y devolverlo después.

## Límites conocidos

- **Digest con `entry_id` negativo.** `pending_digests` no tiene columna para
  el evento ni destinatario en su único, así que las filas del despachador
  codifican `-(event_id * 100 + posición del destinatario)`
  (`event_dispatch.entry_id_de_digest`). Más de 99 destinatarios por evento, o
  ids de evento por encima de ~21 millones, se quedan sin línea de digest (la
  campana sí llega; queda `event_dispatch_digest_sin_hueco` en el log). Una
  columna propia lo retira.
- **Recursos enlazados tarde.** El cursor de `resoluciones_recurso` es por id:
  una resolución que se enlaza a su expediente después de entrar no avisa.
