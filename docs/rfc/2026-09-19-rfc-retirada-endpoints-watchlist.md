---
rfc: 2026-09-19-retirada-endpoints-watchlist
title: Retirada de los endpoints antiguos de seguimiento (favoritos, empresas vigiladas y descartes) en favor de `/follows`
issue: (sin issue: T1 del plan de arquitectura 2026-09 v2, ADR-031 §B fase 3)
author: agent:claude-code
date: 2026-09-19
status: draft
retirada_propuesta: 2027-01-15
---

## Contexto

Seguir algo estaba implementado tres veces, con tres tablas y tres juegos de
endpoints (ADR-031 §Contexto). T1 las unificó en la tabla `follows` (v130) con
el plan de tres fases de ADR-031 §B:

1. **Aditiva — hecha.** `follows` existe, la rellenó el backfill de v130 y las
   tres tablas de origen la mantienen al día por escritura doble
   (`db/repositories/follows.py::registrar`/`olvidar`, llamadas desde
   `watchlist_items`, `watchlist_empresas` y `radar_dismissals`).
   `GET/POST/DELETE /api/v1/follows` sirve lo que antes no existía (seguir
   órganos y CPV).
2. **Lectura desde `follows` — código listo, apagada.** Con
   `FOLLOWS_LECTURA=true` los tres endpoints de lectura antiguos deciden **qué**
   sigue el usuario leyendo `follows`; la tabla de origen sólo aporta las
   columnas que `follows` no tiene (`db/repositories/follows.py`, sección
   «Lectura desde `follows`»). El frontend ya usa un único control
   (`web/src/components/seguir-boton.tsx` sobre `web/src/hooks/use-seguimiento.ts`)
   en Radar, /detalle, Competidores y Órganos.
3. **Retirada** de los endpoints antiguos. Es lo que propone este RFC.

Endpoints afectados (diez operaciones; el plan hablaba de «nueve» porque no
contaba la nota del favorito, que entró después con C6.6):

| Operación | Handler | Tabla de origen |
|---|---|---|
| `GET /api/v1/watchlist/items` | `api/routes/watchlist_items.py::get_items` | `watchlist_items` |
| `POST /api/v1/watchlist/items` | `api/routes/watchlist_items.py::post_item` | `watchlist_items` |
| `DELETE /api/v1/watchlist/items/{id_externo}` | `api/routes/watchlist_items.py` | `watchlist_items` |
| `PUT /api/v1/watchlist/items/{id_externo}/nota` | `api/routes/watchlist_items.py` | `watchlist_items.nota` |
| `GET /api/v1/competitive/watchlist` | `api/routes/competitive.py::get_watchlist` | `watchlist_empresas` |
| `POST /api/v1/competitive/watchlist` | `api/routes/competitive.py::post_watchlist` | `watchlist_empresas` |
| `DELETE /api/v1/competitive/watchlist/{empresa_id}` | `api/routes/competitive.py::delete_watchlist` | `watchlist_empresas` |
| `GET /api/v1/radar/dismissals` | `api/routes/radar.py::get_dismissals` | `radar_dismissals` |
| `POST /api/v1/radar/dismissals` | `api/routes/radar.py` | `radar_dismissals` |
| `DELETE /api/v1/radar/dismissals/{id_externo}` | `api/routes/radar.py` | `radar_dismissals` |

Tres de ellas (`/watchlist/items` GET/POST/DELETE) están además en el contrato
público (`api/contrato_publico.py`), así que las usan —o pueden usarlas—
clientes con API key, no sólo el frontend.

## Por qué esto necesita un RFC

Es un cambio incompatible del contrato API público (AGENTS.md §5, política de
RFCs): se eliminan operaciones publicadas, y tres de ellas están en el contrato
que se promete a integradores. Además arrastra, en una fase posterior, el
borrado de tres tablas con datos de usuario.

## Propuesta

### Precondiciones (todas, antes de anunciar fecha)

1. `scripts/check_follows_paridad.py` contra producción con **cero** filas que
   falten o sobren en los tres pares de `PARES_DE_ORIGEN`, en dos pasadas
   separadas al menos una semana (el job `scheduler/jobs/follows_paridad.py`
   lo mide a diario).
2. `FOLLOWS_LECTURA=true` en producción **al menos 30 días** sin incidencias
   de «me ha desaparecido un favorito / una empresa / un descarte».
3. `follows` tiene donde guardar lo que hoy sólo vive en las tablas de origen.
   Hoy **no**: falta una migración (fuera del alcance de este RFC) que añada
   a `follows` como mínimo:
   - la **nota personal** del favorito (`watchlist_items.nota`, C6.6);
   - el **canal de la alerta** de empresa (`watchlist_empresas.email`,
     `frequency`, `last_notified_at`) — `channels_json` ya existe y es el
     sitio natural;
   - la **acción y el score** del descarte (`radar_dismissals.accion`,
     `score`, `banda`; `hasta` ya está en `follows`).
   Sin eso, retirar las tablas de origen pierde datos del usuario, que es lo
   que ADR-031 §B prohíbe.
4. Los consumidores internos que leen las tablas de origen sin pasar por la
   API migran a `follows`: `WatchlistRepository.calendar_items` (ICS),
   `services/deadline_reminders.py`, `db/watchlist_empresas.py::list_all`
   (alertas de competidores del scheduler) y
   `db/radar_dismissals.py::pospuestos_vencidos` (recordatorios F5.6).

### Calendario

- **T0** (precondiciones 1–4 cumplidas): las diez operaciones pasan a
  `deprecated=True` en OpenAPI y responden con `Deprecation` y
  `Sunset: <T0 + 90 días>` (mismo mecanismo que
  `2026-09-06-rfc-retirada-endpoints-analitica`). El frontend deja de
  llamarlas: `useSeguimiento` enruta todos los tipos a `/follows` (la tabla de
  enrutado de su cabecera se reduce a su última fila) y `SeguirBoton` no
  cambia.
- **T0 + 90 días** (fecha propuesta mínima: **2027-01-15**): las diez
  operaciones responden `410 Gone` con un cuerpo que apunta a `/follows`.
- **T0 + 180 días**: se retiran los handlers, la escritura doble y, en una
  revisión alembic propia con su ventana, las tres tablas de origen.

## Alternativas descartadas

- **Mantener los endpoints viejos como fachada de `follows` para siempre.**
  Barato hoy, pero congela tres contratos que no se pueden extender (seguir un
  órgano no cabe en `/watchlist/items`) y deja la tentación de volver a leer
  de la tabla de origen «porque ya está ahí».
- **Retirar ya, con la lectura encendida y sin migrar las columnas que faltan.**
  Pierde la nota del favorito y el canal de alerta de empresa: pérdida de datos
  del usuario, prohibida por ADR-031 §B.
- **Cambiar la escritura del frontend a `/follows` antes de retirar.** Hoy
  `POST /follows` no escribe en las tablas de origen, así que un favorito
  marcado así no aparecería en «Mi watchlist» ni en el ICS mientras esas
  lecturas no se muevan. Por eso `useSeguimiento` enruta por tipo hasta T0.

## Consecuencias

- Integradores con API key que usen `/watchlist/items` tienen 90 días desde T0
  para pasar a `/follows` (`target_type=licitacion`, `kind=seguir`). El
  mapeo es uno a uno salvo la nota, que llegará con la migración de la
  precondición 3.
- Se retiran tres tablas y la escritura doble: menos código y un solo sitio que
  responder a «¿quién sigue esto?» (ADR-031 §D).
- `check_user_key_ratchet` baja: `db/watchlist_empresas.py` y
  `db/radar_dismissals.py` dejan de existir como consultas por `user_key`.

## Verificación

- Paridad: `PYTHONPATH="$PWD" python scripts/check_follows_paridad.py` a cero.
- Lectura: `tests/test_follows_lectura.py` (SQL por los dos lados del flag) y
  `tests/test_follows_lectura_integration.py` (mismas filas desde las dos
  tablas, contra Postgres).
- Control único: `web/src/hooks/__tests__/use-seguimiento.test.tsx`.
- Tras T0: `make check-api-contract` con las diez operaciones marcadas
  `deprecated`, y ninguna llamada a ellas en `web/src` (`rg` en CI).
