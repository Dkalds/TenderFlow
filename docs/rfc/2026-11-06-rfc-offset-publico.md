---
rfc: 2026-11-06-offset-publico
title: "Acotar el `offset` de `/publico` y paginar el sitemap por cursor"
issue: "(sin issue: P2 «Auditoría del 2026-11-04: lo que quedó pendiente de migración o de decisión» de docs/IMPROVEMENT_BACKLOG.md, viñeta «API pública»)"
author: agent:claude-code
date: 2026-11-06
status: draft
related:
  - "[[ADR-035-camino-de-peticion-sin-bloquear-el-event-loop]]"
---

## Problema

Las dos rutas paginadas de la superficie pública, que no piden sesión, aceptan
desplazamientos muy por encima de lo que existe:

| Ruta | Parámetro hoy | Orden |
|---|---|---|
| `GET /publico/licitaciones` | `offset` `le=1_000_000`, `limit` ≤ 100 | `fecha_publicacion DESC NULLS LAST, id_externo` |
| `GET /publico/sitemap/entradas` | `offset` `le=10_000_000`, `limit` ≤ 50.000 | `id_externo` |

Las dos leen `licitaciones_canonicas` con `LIMIT … OFFSET`. Medido el
2026-11-06 en producción: la vista tiene ~106.000 filas (`reltuples`) sobre
126.130 licitaciones. Un `OFFSET` no salta filas, las lee y las descarta, así
que cualquier `offset` por encima de ~106.000 recorre la vista entera para
devolver una página vacía. En el listado además ordena la vista completa: con
`OFFSET 1_000_000` el *top-N heapsort* no sirve y Postgres ordena todo.

No es una puerta abierta: el coste está acotado por el tamaño de la vista (no
por el número pedido), la respuesta lleva `Cache-Control` público y el límite
por IP (cuando el RFC 2026-10-24 de la IP del cliente se verifique) frena la
repetición. Pero es la consulta más cara que un anónimo puede pedir, y el
techo del parámetro no guarda relación con ningún dato.

El acceso a la vista no lo tiene el MCP de solo lectura, así que la duración
de una página profunda **no está medida**; medirla es el paso 1 del plan.

## Por qué RFC

Bajar el `le` de un parámetro es cambio incompatible según
[docs/api-design.md](../api-design.md) («Qué cuenta como cambio incompatible»),
y `scripts/check_api_breaking.py` lo detecta: lleva la etiqueta `api-breaking`
y esta RFC enlazada.

## Propuesta

1. **Listado** (`/publico/licitaciones`): `offset` `le=250_000`. Deja más del
   doble de margen sobre la vista actual; el hub del frontend pagina de 50 en
   50 y no enlaza más allá de la última página que da `total`.
2. **Sitemap** (`/publico/sitemap/entradas`): añadir `despues_de` (el último
   `id_externo` del tramo anterior, opcional) y resolver el tramo con
   `WHERE c.id_externo > %s ORDER BY c.id_externo LIMIT %s`, que el índice
   único de la vista sobre `id_externo` resuelve sin descartar filas. El
   `offset` se queda con `le=1_000_000` y `Deprecation`/`Sunset` (política de
   api-design.md) hasta que `web/src/lib/publico-api.ts` use el cursor; después
   se retira.
3. Fuera de alcance: cambiar el orden de ninguna de las dos rutas (el del
   sitemap existe para que cada URL caiga siempre en el mismo fichero).

Alternativa descartada: contestar 200 con la página vacía sin consultar cuando
`offset ≥ total`. No cambia el contrato, pero `total` también recorre la vista
y el listado lo calcula en cada petición: ahorra una de las dos lecturas, no la
cara.

## Plan

1. Medir con `EXPLAIN (ANALYZE, BUFFERS)` en producción la página con
   `offset` 0, 100.000 y 1.000.000 de las dos rutas (rol con acceso a la vista).
2. Si la profunda tarda más de ~200 ms, aplicar 1 y 2 en un PR con la
   etiqueta `api-breaking`; si no, cerrar esta RFC como `rejected` con la
   medición, y bajar el ítem del backlog.
3. Test de contrato: `offset=250_001` es 422 en el listado; `despues_de` de un
   tramo devuelve exactamente el tramo siguiente del `offset` equivalente.

## Decisión pendiente

Del propietario: aprobar (`approved`) o descartar tras la medición del paso 1.
