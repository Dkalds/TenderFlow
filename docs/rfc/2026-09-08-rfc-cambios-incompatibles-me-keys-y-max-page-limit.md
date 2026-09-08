---
rfc: 2026-09-08-me-keys-y-max-page-limit
title: Dos cambios incompatibles del contrato - el sobre de /me/keys y el tope universal de paginacion
issue: (sin issue: los pide el plan complementario 2026-09, items C2.3 y C8.5)
author: agent:claude-code
date: 2026-09-08
status: implemented
implemented_on: 2026-09-08
implemented_evidence: >
  `api/routes/me.py::MyApiKeysResult` (sobre con `tier`), `shared/dto.py::MAX_PAGE_LIMIT`
  y su adopcion en `api/routes/admin_users.py` y `api/routes/competitive.py`.
  El detector de `scripts/check_api_breaking.py` los lista en la PR #288, que es
  donde esta RFC se enlaza con la etiqueta `api-breaking`.
---

## Contexto

`scripts/check_api_breaking.py` (C8.2) hace exactamente lo que se le pidió:
detecta siete cambios incompatibles en la PR que integra el plan complementario
sobre `master`. La política de `docs/api-design.md` dice que un cambio así no se
mergea sin etiqueta y sin una RFC enlazada, porque **romper el contrato sin
dejar rastro escrito no es una opción**. Este documento es ese rastro.

Los siete son dos cambios, no siete: cinco líneas del informe son el mismo
cambio de forma en `GET /me/keys`, y dos son el mismo tope de paginación
aplicado a dos rutas.

## 1. `GET /me/keys` pasa de array a sobre

**Antes:** `[{id, name, created_at, expires_at, is_active}]`.
**Ahora:** `{items: [{id, name, tier, is_active, created_at, expires_at}]}`.

El detector lo lee como «la respuesta pierde `[].id`, `[].name`,
`[].created_at`, `[].expires_at`, `[].is_active`». No se pierde ninguno: los
cinco viven ahora dentro de `items`, y hay uno más — `tier`.

### Por qué

`tier` es **criterio de aceptación de C2.3**: la columna `api_keys.tier` existe
desde `v28` y ninguna ruta la leía, así que el usuario no podía saber con qué
límite de rate limit se le iba a aplicar su propia clave. Publicarla obliga a
tocar la respuesta.

Y una vez que hay que tocarla, el sobre es la forma correcta. Un array desnudo
no admite metadatos: el día que esta ruta necesite paginar, o decir cuántas
claves caducan pronto, habría que volver a romperla. El resto del contrato ya
usa sobres para esto (`Paginated[T]`, `WebhookEventTypes`,
`RadarDismissalsResult`), así que esto además lo alinea en vez de apartarlo.

### Quién lo consume, y por qué no rompe

Los dos consumidores están en este repositorio:

- `web/src/app/(dashboard)/ops/_hooks/use-api-keys.ts` ya leía
  `keysData?.keys ?? keysData?.items ?? []` — el sobre era una de las formas que
  aceptaba antes de que existiera.
- `web/src/hooks/use-ajustes.ts` (C7.5) lo consume tipado como
  `MyApiKeysResult`.

No hay consumidores externos: `/me/keys` exige sesión o API key propia y no
figura en ningún SDK publicado.

### Retirada

No hay período de deprecación porque no hay nada que deprecar: la forma anterior
no se sirve en paralelo. La alternativa —mantener el array y añadir `tier` en una
ruta hermana— dejaría dos endpoints que dicen lo mismo con distinta forma, que
es peor contrato que uno que cambió una vez y quedó documentado.

## 2. `limit` baja su máximo de 1000 a 500

Afecta a `GET /api/v1/admin/users` y a `GET /api/v1/competitive/renovaciones`.

Es **C8.5**, que lo pide literalmente: «`MAX_PAGE_LIMIT` universal:
`/competitive/renovaciones` deja de aceptar `le=1000`». El tope vive ahora en
`shared/dto.py::MAX_PAGE_LIMIT` y no como un literal por ruta, que era lo que
permitía que cada endpoint eligiera el suyo.

### Por qué 500 y no 1000

Un `limit` que nadie acota es una forma de pedirle a la base de datos un escaneo
grande desde fuera. 500 filas cubren cualquier pantalla del producto —el tablero
más denso pinta 100— y dejan margen para un export razonable; por encima, lo que
se quiere es el export, que tiene su propia ruta y su propio camino asíncrono.

### Efecto real

Una petición con `limit=1000` deja de recibir 1000 filas y pasa a recibir un 422
de validación. **No trunca en silencio**, que es lo que importa: quien pedía
1000 se entera, en vez de recibir 500 creyendo que eran todas.

Ningún consumidor del repositorio pide más de 500: los dos hooks que llaman a
estas rutas usan el `limit` por defecto.

## Alternativas descartadas

- **No publicar `tier`** y dejar C2.3 a medias. Descartada: el ítem existe
  justo porque una columna sin lector es una funcionalidad que no existe.
- **Etiquetar la PR y no escribir esta RFC.** El propio gate lo impide, y con
  razón: la etiqueta dice «es deliberado», la RFC dice «y este es el motivo».
- **Subir `MAX_PAGE_LIMIT` a 1000** para no romper nada. Sería elegir el tope
  más laxo de los que había en vez de uno pensado, y dejaría el ítem C8.5 sin
  contenido.
