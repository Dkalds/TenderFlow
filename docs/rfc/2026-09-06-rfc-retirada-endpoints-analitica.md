---
rfc: 2026-09-06-retirada-endpoints-analitica
title: Retirada de tres endpoints de analítica sin consumidor y del listado por offset
issue: (sin issue: decisión D19 del plan de arquitectura 2026-09 v2)
author: agent:claude-code
date: 2026-09-06
status: approved
retirada_efectiva: 2026-12-04
---

## Contexto

Cuatro operaciones publicadas del contrato no las usa nadie, y sostenerlas cuesta
más que el valor que dan.

Las tres primeras son de analítica y **no tienen un solo consumidor en el
frontend**. Medido el 2026-09-05 sobre `web/src` (hecho 9 del plan
[2026-09-plan-arquitectura-v2.md](../plans/2026-09-plan-arquitectura-v2.md)):
`web/src/lib/analytics.ts:40-46` las declara en el cliente tipado y ningún
componente llama a esas tres funciones.

| Operación | Handler |
|---|---|
| `GET /api/v1/analytics/compare-periods` | `api/routes/analytics.py::compare_periods` |
| `GET /api/v1/analytics/resumen/sankey` | `api/routes/analytics.py::resumen_sankey` |
| `GET /api/v1/analytics/resumen/top` | `api/routes/analytics.py::resumen_top` |

La cuarta es distinta: **sí se usa**, pero está sustituida.
`GET /api/v1/licitaciones` pagina por offset, y `GET /api/v1/licitaciones/cursor`
—que el propio `summary` marca como recomendado desde que existe— pagina por
cursor estable `(fecha_publicacion, id_externo)`. Mantener las dos significa
mantener dos caminos de paginación sobre la misma consulta caliente, con la
particularidad de que el que sobra es el que se degrada con el tamaño de la
tabla: un `OFFSET` grande sobre `licitaciones` obliga a Postgres a descartar
filas ya leídas.

Hasta hoy el listado por cursor exigía `require_api_key`, así que el frontend
**no podía** migrar aunque quisiera. Eso se corrige en el mismo cambio que este
RFC acompaña (apartado b de O0.6): las cuatro rutas de `api/routes/licitaciones.py`
que exigían API key pasan a `require_any_auth`. Sin ese arreglo previo, anunciar
la retirada del listado por offset habría sido anunciar la retirada del único
listado que una sesión de navegador podía consumir.

## Por qué esto necesita un RFC

AGENTS.md §5 exige RFC formal para «cambios breaking al contrato API público
(campos eliminados, semántica cambiada)». Borrar cuatro operaciones lo es, con
independencia de cuántos clientes se sepa que las usan: el contrato es público y
puede haber integraciones por API key fuera de nuestra vista.

## Decisión

Retirada anunciada en dos tiempos, con 90 días entre el anuncio y el borrado.

**Fase 1 — hoy, 2026-09-06.** Las cuatro operaciones se marcan `deprecated=True`
en FastAPI y su `summary` empieza por `[DEPRECADO 2026-12-04]`. El
comportamiento **no cambia**: siguen respondiendo exactamente lo mismo. La marca
viaja en el OpenAPI, así que aparece tachada en `/docs` y el cliente TS generado
la refleja, que es la única forma de avisar a un integrador que no lee el
repositorio.

**Fase 2 — a partir del 2026-12-04.** Se borran los cuatro handlers, sus
funciones de servicio si no quedan otros llamadores, y las entradas de
`web/src/lib/analytics.ts`. El borrado va en su propia PR, citando este RFC.

## Alternativas descartadas

- **Borrarlas ya.** Es lo que el coste de mantenimiento pediría, y es
  precisamente lo que la política de RFC impide: un contrato público no se
  rompe sin ventana de aviso porque el emisor crea saber quién lo consume.
- **Dejarlas y no tocar nada.** Es el estado actual: tres endpoints que nadie
  llama compitiendo por el mismo caché de `@cache_response`, y dos paginaciones
  para la misma consulta. El coste no es el CPU, es que cada refactor de
  `services/analytics/` y de `db/repositories/licitaciones.py` tiene que
  seguir preservando caminos muertos.
- **Retirar solo las tres de analítica y conservar el offset.** Deja a medias lo
  que motiva el cambio. El listado por offset es el que tiene coste real en
  producción; las tres de analítica solo tienen coste de mantenimiento.

## Consecuencias

- Antes del 2026-12-04, el frontend tiene que dejar de usar
  `GET /licitaciones` por offset. Es posible desde este mismo cambio, porque
  `/licitaciones/cursor` ya acepta sesión.
- `docs/api-design.md` y el cliente `web/src/lib/analytics.ts` se actualizan en
  la PR de la fase 2, no en esta.
- Si antes de la fecha aparece un consumidor real de alguna de las cuatro, este
  RFC se revisa: la fecha es un compromiso, no un automatismo.

## Verificación

- `python scripts/export_openapi.py` y después comprobar que las cuatro
  operaciones llevan `"deprecated": true` en `api/openapi.json`.
  Lo fija `tests/test_o06_contrato_api.py::test_las_cuatro_operaciones_estan_deprecadas`.
- El ratchet de contrato sigue verde:
  `python scripts/check_openapi_contract.py`.
