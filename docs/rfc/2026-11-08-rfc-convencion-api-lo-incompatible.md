---
rfc: 2026-11-08-convencion-api-lo-incompatible
title: "Lo que la convención de la API dejó congelado: sobres de paginación, `type` de error por condición e idioma de las rutas"
issue: "(sin issue: P2 «Fijar la convención de la API pública antes de más consumidores: idioma, errores y una sola paginación» de docs/IMPROVEMENT_BACKLOG.md, apartado «Queda (pide RFC, es incompatible)»)"
author: agent:claude-code
date: 2026-11-08
status: draft
related:
  - "[[2026-09-06-rfc-retirada-endpoints-analitica]]"
  - "[[2026-11-06-rfc-offset-publico]]"
---

## Contexto

El 2026-10-25 se fijó la parte compatible de la convención
([docs/api-design.md](../api-design.md), «Convención de la API»): español en lo
nuevo, un solo error (`ProblemDetail`, RFC 9457) y una sola paginación
(`limit`/`offset` con `Pagina[T]`), con lo heredado congelado en
`scripts/check_api_convencion.py`. Lo que quedó fuera es incompatible y pide RFC
(AGENTS.md §5). Dos de esas piezas ya tienen dueño y **no** se tratan aquí:

| Pieza | Dónde se decide |
|---|---|
| Convivencia offset/cursor de `GET /licitaciones` | Decidida: el offset está deprecado con `Sunset` 2027-01-15 y sucesora `GET /licitaciones/cursor` ([RFC 2026-09-06](2026-09-06-rfc-retirada-endpoints-analitica.md)) |
| `GET /publico/sitemap/entradas` | [RFC 2026-11-06](2026-11-06-rfc-offset-publico.md) (cursor `despues_de`) |

Quedan tres decisiones, y este RFC propone las tres.

## Medición (2026-11-08, OpenAPI de `origin/master` `e1e7a817`, 263 paths)

### Los sobres de paginación congelados ya son `Pagina[T]` más contexto

| Operación | Componente | Campos | ¿Contrato público? |
|---|---|---|---|
| `GET /empresas` | `EmpresasListResult` | items, total, limit, offset + sort, order | sí |
| `GET /pursuits` | `PursuitListResponse` | items, total, limit, offset + organization_id | no |
| `GET /pursuits/{id}/comments` | `PursuitCommentListResponse` | items, total, limit, offset + organization_id, pursuit_id | no |
| `GET /radar/proximas` | `RadarProximasResult` | items, total, limit, offset + con_fecha_prevista, estados, fecha_prevista_origen | no |
| `GET /notifications/alerts` | `AlertasPagina` | items, total, limit, offset + sin_leer | no |
| `GET /competitive/empresas/{id}/adjudicaciones` | `CompetitiveCompanyAwardsDTO` | items, total, limit, offset | no |
| `GET /competitive/renovaciones` | `RenovacionesResult` | items + months_ahead; **acepta** `limit`/`offset` pero no los devuelve, ni `total` | no |

Seis de los siete ya llevan las cuatro claves de `Pagina[T]` con los mismos
tipos. Lo que los aparta del gate es el **nombre** del componente
(`_PREFIJO_PAGINA = "PaginatedResponse_"`) y unos campos de contexto que la
pantalla necesita junto a la página (el contador de no leídas de la campana, la
calidad del Radar). En dos casos (`PursuitListResponse.items`,
`CompetitiveCompanyAwardsDTO.total/offset/items`) el esquema los marca opcionales
solo porque el DTO les da valor por defecto: la respuesta siempre los trae.

Los dos cursores también comparten forma: `CursorPaginatedResponse[WithTotal]`
(`items`, `next_cursor`, `has_more`, `limit` y, en el corpus, `total` opcional).

### El `type` del error: uno por código HTTP, y dos para el 429 sin querer

`api/errors.py` emite un `type` por código (`bad-request`, `not-found`,
`conflict`…), salvo `query-timeout` (503) y `reauthentication-required` (403),
que la web compara (`web/src/lib/query-feedback.ts`,
`web/src/lib/reautenticacion.ts`). El 429 sale con **dos** tipos según quién lo
lance, y no por diseño:

| Origen | `type` hoy | `Retry-After` | Qué significa |
|---|---|---|---|
| Middleware de rate limit (`api/middleware.py`) | `rate-limit-exceeded` | sí, la ventana | reintenta tras la ventana |
| Intentos de login, registro, contraseña, TOTP (`api/routes/auth/*`) | `too-many-requests` | no | lo mismo: un límite por ventana |
| Presupuesto LLM agotado (`LLMBudgetExceeded`: `/ask`, pliegos) | `too-many-requests` | no | no reintentes hasta que se renueve el presupuesto |
| Cuota de jobs de exportación (`CuotaDeJobsExcedida`, `/exports`) | `too-many-requests` | no | espera a que acabe un job tuyo |

Un cliente no puede distinguir «espera 60 s» de «no vuelvas hoy» sin leer el
`detail`, que es texto para personas. Conteo aproximado de `HTTPException(` por
código en `api/` (grep, 2026-11-08): 403 ×95, 404 ×81, 422 ×22, 400 ×15,
409 ×13, 429 ×7, 401 ×6. Además dos `detail` del 429 y uno del 403 siguen en
inglés (`auth/login.py`, `auth/totp.py`, `dual_auth.py`), contra la convención.

### Idioma: de lo heredado en inglés, solo `/follows` es contrato público

`api/contrato_publico.py` publica `/follows` (tres operaciones). `/pursuits`,
`/organizations`, `/saved-filters` y `/feature-flags` son internas: su único
consumidor es la web de este repo, aunque se despliega por separado (Vercel y
Render), así que un renombre pide igualmente un periodo con las dos rutas vivas.

## Decisiones propuestas

### 1. Paginación: la convención pasa a ser estructural

**Propuesta (recomendada).** La regla deja de ser «el componente se llama
`PaginatedResponse_…`» y pasa a ser «el sobre **hereda** de `Pagina[T]`»:
`items`, `total`, `limit` y `offset` requeridos, con esos tipos, y se admiten
campos de contexto al lado. Los seis sobres pasan a heredar de
`PaginatedResponse[T]` conservando su nombre:

- **En el cable no cambia nada**: mismos nombres de componente y mismos campos.
  Marcar como requeridos campos que la respuesta ya trae siempre estrecha la
  respuesta, no la petición, y `scripts/check_api_breaking.py` no lo cuenta
  como incompatible.
- `RenovacionesResult` gana `total`, `limit` y `offset` (cambio aditivo). Coste:
  un `count` sobre la consulta de renovaciones; se mide antes de aceptarlo (si
  pasa de 100 ms, `total = -1` con `with_total`, como ya admite `Pagina[T]`).
- `scripts/check_api_convencion.py` comprueba la herencia en el esquema (las
  cuatro claves requeridas y sus tipos) en vez del prefijo del nombre, y
  `PAGINACION_CONGELADA` pierde siete entradas.

**El cursor se reconoce como segunda forma sancionada**, no como excepción:
`CursorPaginatedResponse[T]` para logs append-only y volcados del corpus entero,
que es donde un `OFFSET` profundo cuesta. Una ruta nueva sigue paginando por
offset salvo que un RFC decida lo contrario (lo que ya dice api-design.md). Con
eso `GET /licitaciones/cursor` y `GET /organizations/{id}/audit` salen de la
lista porque cumplen, y en ella solo queda el sitemap, hasta que se cierre su RFC.

*Alternativa descartada:* migrar los siete a `Pagina[T]` a secas y sacar el
contexto a endpoints propios (`/notifications/alerts/sin-leer`…). Rompe el
cliente generado y la web, duplica peticiones en pantallas que hoy hacen una, y
un integrador no gana nada: las cuatro claves que parsea ya están.

### 2. Error: un `type` propio solo donde el cliente actúa distinto

**Regla.** El `type` por código HTTP sigue siendo el de defecto. Un `type`
específico existe **solo** cuando un cliente tiene que hacer algo distinto que
con el genérico (reintentar tras una espera, no reintentar, volver a
autenticarse). Los tipos viven en un catálogo cerrado en `api/errors.py` (una
constante por tipo con su código y su significado), y la tabla de
[docs/api-design.md](../api-design.md) se genera desde él.

**Catálogo inicial**: los dos que ya existen y el 429 partido por lo que
significa.

| `type` | Código | Qué hace el cliente | Quién lo emite |
|---|---|---|---|
| `rate-limit-exceeded` | 429 | Reintenta pasado `Retry-After` | middleware, y desde ahora login, registro, contraseña y TOTP (con `Retry-After` donde la ventana se conozca; está por comprobar en cada uno) |
| `budget-exhausted` | 429 | No reintenta hasta que se renueve el presupuesto; `detail` dice cuándo | `LLMBudgetExceeded` |
| `quota-exceeded` | 429 | Espera a que termine un trabajo propio | `CuotaDeJobsExcedida` |
| `query-timeout` | 503 | No reintenta la misma consulta: la acota | ya existe |
| `reauthentication-required` | 403 | Vuelve a entrar | ya existe |

`too-many-requests` desaparece. **Es un cambio de valor en un campo del
contrato** que `check_api_breaking.py` no ve, así que va con la misma ventana de
90 días que una ruta: se anuncia en una tabla nueva «Cambios de `type`» de
api-design.md con su fecha efectiva, y la web (que no compara ese valor hoy) no
necesita cambios. Los 403 y 409 no entran todavía: entran cuando se inventaríen
sus condiciones (paso 3) y solo las que pasen la regla de arriba.

Los `detail` en inglés pasan a castellano en el mismo cambio. El texto no es
contrato, así que eso no necesita RFC; se agrupa aquí para no tocar dos veces
los mismos manejadores.

### 3. Idioma: no se renombra nada en `/api/v1`

Se confirma lo que dice la convención: lo heredado en inglés se queda en v1.

- `/follows` es contrato público. Renombrarlo cuesta 90 días de alias,
  `Sunset`, un SDK nuevo y la migración de cada integrador, y no aporta nada
  funcional.
- Las cuatro internas podrían renombrarse con un periodo corto de alias, porque
  su único consumidor es la web. Pero el coste es el mismo trabajo (rutas
  duplicadas, regenerar `api-types.ts`, cambiar cada llamada) por un beneficio
  estético. No compensa.

Para que una futura `/api/v2` no reabra la discusión, sus nombres quedan
fijados aquí: `/oportunidades` (por `/pursuits`, el término de la interfaz),
`/organizaciones`, `/seguimientos` y `/filtros-guardados`. `/feature-flags` es
una superficie de administración sin término acordado en castellano: su nombre
lo decide quien abra la v2. Ninguna v2 se abre solo por el idioma.

### 4. El 503 de `/health/ready` pasa de congelado a excepción aceptada

Lleva el `HealthResponse` completo porque lo leen el balanceador y los
runbooks. No es deuda: se documenta como excepción permanente en api-design.md,
con su motivo, y sale de la lista de congelados.

## Plan

Cada paso es un PR independiente con `make check-api-convencion`,
`make check-api-contract` y el job `api-breaking-check`.

1. **Paginación estructural.** Los seis DTOs heredan de `PaginatedResponse[T]`;
   el gate pasa a comprobar la herencia y se reconoce el cursor como segunda
   forma. Criterio: OpenAPI idéntico salvo `required`, y
   `PAGINACION_CONGELADA` con una sola entrada (el sitemap).
2. **`RenovacionesResult` con `total`/`limit`/`offset`**, con el coste del
   `count` medido antes.
3. **Catálogo de `type`.** Constantes en `api/errors.py`, los tres tipos del
   429 con `Retry-After` donde corresponde, la tabla generada en
   api-design.md, los `detail` en castellano y la nota de «Cambios de
   `type`» con fecha efectiva a 90 días. Inventario de las condiciones de 403
   y 409 en el mismo PR, con la propuesta de cuáles entran (otra decisión del
   propietario).
4. **Excepción del readiness** y nombres de v2 en api-design.md.

## Preguntas para el propietario

1. ¿Paginación estructural (decisión 1) en vez de migrar los sobres?
2. ¿El catálogo inicial del 429, y retirar `too-many-requests` con aviso de
   90 días?
3. ¿Ningún renombre en `/api/v1`, con los nombres de v2 fijados aquí?
