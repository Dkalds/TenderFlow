# ADR-006: ETag middleware + async PDF export endpoint

**Status:** Accepted  
**Date:** 2026-05-19

## Contexto

La API REST servía respuestas JSON sin cabeceras de cache condicional, lo que
forzaba a los clientes a procesar el cuerpo completo en cada sondeo aunque el
resultado no hubiera cambiado. Además, no había forma de exportar licitaciones
en formato PDF desde la API (sólo desde el dashboard Streamlit).

## Decisiones

### 1. ETagMiddleware (F4)

Se añade `ETagMiddleware` a la cadena ASGI de `api/app.py`. Calcula un `W/`
(weak) ETag como `SHA-1[:24]` del cuerpo de respuestas `GET 200 application/json`
de hasta 512 KB. Responde `304 Not Modified` si `If-None-Match` coincide.

Alternativas descartadas:
- ETags en cada router individualmente: más código, fácil de olvidar.
- `Last-Modified` en lugar de ETag: requiere timestamp fiable por recurso.

Consecuencias:
- Reducción de ancho de banda para clientes que sondean `/api/v1/models`,
  `/api/v1/licitaciones/{id}`, etc. con frecuencia.
- SHA-1 se usa sólo como hash de contenido (no criptográfico); el riesgo de
  colisión intencional es nulo en este contexto.

### 2. Endpoint de exportación PDF asíncrona (F5)

`POST /api/v1/exports` acepta filtros opcionales (`ccaa`, `estado`, `q`),
crea un job en memoria y devuelve `202 Accepted` con `{id, status}`.
`GET /api/v1/exports/{id}` devuelve el PDF cuando el job finaliza.

El PDF se genera con `reportlab` (ya declarado como dependencia principal).
El almacén de jobs es un dict en memoria con TTL 15 min; suficiente para
instancia única. Para multi-instancia se requeriría Redis o una tabla DB.

Límite: 500 filas por exportación para evitar PDFs imposibles de imprimir.

### 3. Rate limiting Redis como dispatcher (F4)

`RateLimitMiddleware` ahora delega en `services.rate_limit_redis.check_rate_limit`,
que actúa como dispatcher: usa Redis si `RATE_LIMIT_BACKEND=redis` y Redis está
accesible, o cae al backend SQLite existente. Sin configuración adicional, el
comportamiento es idéntico al anterior.

## Consecuencias positivas

- Cache condicional sin cambios en los clientes existentes.
- Exportación PDF disponible via API para integraciones externas.
- Path de escalado de rate limiting sin cambiar la interfaz pública.
