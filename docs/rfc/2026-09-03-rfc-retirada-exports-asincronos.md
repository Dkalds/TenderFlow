---
rfc: 2026-09-03-retirada-exports-asincronos
title: Retirada de los tres endpoints de export asíncrono y de su almacén en memoria
issue: (sin issue: decisión D7 del plan de arquitectura 2026-09)
author: agent:claude-code
date: 2026-09-03
status: implemented
implemented_on: 2026-09-18
implemented_evidence: "`api/routes/exports.py` ya no declara `POST /exports` ni `GET` o `DELETE /exports/{job_id}`, y `tests/test_export_openapi.py` fija que `/api/v1/exports` y `/api/v1/exports/{job_id}` no están en el esquema. El sustituto, `GET /exports/download?format=pdf`, anuncia `application/pdf` en su 200. Retirada entregada en #265 (`88d7c7c0`, 2026-09-04); deprecación previa en `9207bde9` (2026-07-28)."
---

> **Reconstruido el 2026-09-18.** Cuatro módulos (`api/routes/exports.py`,
> `api/app.py`, `shared/cache.py` y `tests/test_unit_export_idor.py`) citaban
> este fichero desde el 2026-09-03 y el fichero no se llegó a escribir (backlog
> P3 «Cuatro módulos citan un RFC de retirada de exports que no existe»). El
> contenido sale de la decisión D7 de
> [2026-09-plan-arquitectura.md](../plans/2026-09-plan-arquitectura.md), del
> commit que deprecó los endpoints (`9207bde9`) y del que los retiró
> (`88d7c7c0`, PR #265). No añade decisiones: registra las que ya se tomaron.

## Contexto

Hasta el 2026-09-03 la API publicaba tres operaciones para exportar a PDF en
dos tiempos:

| Operación | Qué hacía |
|---|---|
| `POST /api/v1/exports` | Aceptaba el trabajo y respondía `202` con un id. |
| `GET /api/v1/exports/{job_id}` | Sondeo: `202` mientras se generaba, el fichero al acabar. |
| `DELETE /api/v1/exports/{job_id}` | Cancelaba o borraba el trabajo. |

El estado de cada trabajo —y los bytes del PDF— vivía en un `dict` del proceso
(`_store`, TTL de 900 s, tope de 100 trabajos). El código lo justificaba como
«suficiente para un servicio de una sola instancia», y esa premisa **no se
cumple en el despliegue real**:

- el plan de Render recicla la instancia en reposo, así que un trabajo aceptado
  con `202` desaparecía y el sondeo devolvía `404` sin que nada lo registrara
  como fallo;
- con más de un worker o más de una instancia, `POST` y `GET` caían en procesos
  distintos y el sondeo daba `404` o `403` de forma no determinista.

Ese mismo `dict` fue la superficie del IDOR de
[RFC 050](050-idor-export-jobs.md) (issue #50): un id adivinable apuntando al
trabajo de otro usuario.

El 2026-07-28 (`9207bde9`) se añadió el camino que lo sustituye —`GET
/exports/download` ganó `format=pdf` y devuelve el documento en la propia
respuesta— y los tres endpoints se marcaron `deprecated=True`, visibles así en
Swagger y en `web/src/generated/api.d.ts`. No se borraron entonces porque
hacerlo es un cambio incompatible del contrato público, que según AGENTS.md §5
pide RFC.

## Decisión

D7 del plan de arquitectura de septiembre ofrecía dos salidas: retirar los
endpoints del contrato o mover `_store` a la caché compartida
(`shared/cache.py`, namespace `exports`, TTL 900 s). **Se decidió retirar** el
2026-09-03, y se ejecutó en el mismo plan (#265, `88d7c7c0`, mergeado el
2026-09-04):

- `POST /exports`, `GET /exports/{job_id}` y `DELETE /exports/{job_id}` salen
  del router y del esquema OpenAPI.
- El almacén en memoria se va con ellos; `shared/cache.py` deja de listarlo en
  su tabla de capas de caché.
- `tests/test_export_openapi.py` fija que las dos rutas no reaparecen en el
  esquema y que la descarga síncrona sigue anunciando `application/pdf`.
- `tests/test_unit_export_idor.py` se reescribe: el invariante de #50 —nadie se
  descarga la exportación de otro— se comprueba sobre el diseño que queda, en
  vez de desaparecer con el `dict`.

**Sustituto:** `GET /api/v1/exports/download?format=pdf`, que ya existía desde
julio y devuelve el PDF en la misma respuesta, igual que CSV y Excel.

**Qué no se decidió:** que el 202+sondeo no pudiera volver nunca. El motivo de
la retirada era el estado en un proceso, no el patrón. Volvió el 2026-09-16
(#311) para los PDF por encima de `JOBS_EXPORT_UMBRAL_FILAS`, con las dos cosas
que faltaban: el estado en la tabla `jobs` (v2 S5) y el binario en la caché
compartida, y comprobación de organización en cada lectura. Lo sirve una ruta
distinta, `GET /exports/descargas/{job_id}`, para que `/download` siga sin
aceptar identificadores.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Mover `_store` a `shared/cache.py` (Redis) | Conserva el contrato; sin cambio incompatible | Mantiene una máquina de estados para un caso que la descarga síncrona ya cubría; el PDF entero en Redis por trabajo | No había consumidor que necesitara el 202: el frontend ya descargaba en síncrono |
| Dejarlos `deprecated` sin fecha | Ningún cliente se rompe | Endpoints que fallan de forma no determinista siguen publicados y documentados | Un endpoint que devuelve 404 al azar es peor que uno que no existe |
| Retirar (elegida) | Elimina la clase de fallo y la superficie del IDOR | Cambio incompatible para quien siguiera llamándolos | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Ninguno | — |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno | — |
| §3.4 Auto-marking tests | Ninguno | — |
| §3.5 Pydantic v2 DTOs | Tres operaciones salen del contrato | Deprecadas desde el 2026-07-28; el sustituto estaba publicado antes de retirarlas |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

Ejecutado en #265 (`88d7c7c0`):

1. `api/routes/exports.py`: fuera los tres handlers, `_store`, su lock y la
   purga por TTL.
2. `api/app.py` y `shared/cache.py`: docstrings actualizados para decir qué se
   retiró y remitir aquí.
3. `tests/test_export_openapi.py`, `tests/test_routes_exports.py`,
   `tests/test_unit_export_idor.py`: fijan la retirada y el invariante de #50.

**Archivos de partida**: `api/routes/exports.py`, `services/exports.py`
**Riesgo estimado**: bajo

## Acceptance criteria

- [x] Las tres operaciones no están en el esquema OpenAPI (`tests/test_export_openapi.py`).
- [x] `GET /exports/download?format=pdf` devuelve el PDF en la respuesta.
- [x] Ningún módulo conserva estado de exportación en memoria del proceso.
- [x] Los cuatro módulos que citan este RFC apuntan a un fichero que existe.
