# ADR-035 — El camino de cada petición no bloquea el event loop: cuota en Redis por defecto, ETag al cachear y consulta cancelada como 503

- **Estado:** aceptado
- **Fecha:** 2026-09-25
- **Revisa:** [ADR-006](ADR-006-etag-pdf-export-ratelimit-redis.md) §1 (cómo se
  calcula el ETag) y §3 (qué backend de cuota se usa sin configuración).
- **Relacionado:** [ADR-025](ADR-025-construccion-de-sql-y-pools.md) (pools de
  lectura y escritura), [ADR-034](ADR-034-rls-por-tenant.md) (ámbito por
  organización en cada lectura).

---

## Contexto

La API de producción es **un solo proceso uvicorn con un solo event loop**
(`docker/Dockerfile.api`, `--workers 1`) sobre una vCPU. En ese modelo, cualquier
E/S síncrona que se ejecute en el loop no retrasa solo a su petición: para a
todas las del proceso mientras dura.

La revisión de rendimiento de septiembre de 2026 encontró tres casos en el
camino que recorre **cada** petición:

1. **La cuota.** `RateLimitMiddleware` era un `BaseHTTPMiddleware` asíncrono que
   llamaba de forma síncrona a `check()`. Sin `RATE_LIMIT_BACKEND` —y ni
   `render.yaml` ni el servicio real lo fijan—, ADR-006 §3 dejaba la cuota en
   la tabla `rate_limits`: checkout del pool de escritura y BEGIN, DELETE,
   SELECT COUNT, INSERT y COMMIT, unos cinco viajes a Supabase **con el loop
   parado**, en serie para todas las peticiones concurrentes. Una carga del
   Resumen son unas veinte.
2. **La caché de respuestas.** `cache_response` hacía el GET/SET de Redis y la
   (de)serialización JSON dentro del wrapper asíncrono, y el cliente Redis no
   tenía `socket_timeout`: un Redis colgado congelaba el proceso entero.
3. **El ETag.** ADR-006 §1 lo calcula sobre el cuerpo de cada GET JSON, lo que
   obligaba a retener la respuesta entera en el middleware aunque saliera de
   una caché que ya conocía ese cuerpo.

A eso se sumaba que una consulta cancelada por `statement_timeout` salía como
500, el navegador la trataba como fallo transitorio y la reintentaba cuatro
veces: cinco consultas de hasta 30 s contra el mismo pool por una pantalla que
acababa en error igualmente.

## Decisión

1. **La cuota se decide en un hilo, nunca en el loop**
   (`anyio.to_thread.run_sync` con un `CapacityLimiter` propio de 4 hilos, que
   además acota las conexiones de escritura que el limitador puede retener
   cuando cae a la BD). Se descarta `redis.asyncio`: el respaldo de BD es
   psycopg síncrono y habría que llevarlo a un hilo igualmente, y el protocolo
   `RateLimiter` lo comparten otros consumidores síncronos.
2. **`RATE_LIMIT_BACKEND` pasa a valer `auto` por defecto** (revisa ADR-006 §3):
   Redis si `REDIS_URL` está configurada y responde, la tabla `rate_limits` si
   no. `db` y `redis` explícitos siguen funcionando, y un Redis caído entra en
   un enfriamiento de 30 s en vez de reintentar la conexión en cada petición.
   Un error de Redis nunca abre la cuota: esa comprobación la resuelve la BD.
3. **La caché de respuestas no hace E/S en el loop** (`aget`/`aset`, cliente
   Redis con `socket_timeout` y breaker de 15 s) y guarda el cuerpo ya
   serializado junto a su **ETag, calculado una vez al guardar** (revisa
   ADR-006 §1). El middleware respeta el ETag que ya trae una respuesta: no la
   retiene ni la hashea, solo compara con `If-None-Match`. Para las respuestas
   sin ETag previa el hash pasa a BLAKE2b de 16 bytes (`shared/etag.py`), con el
   mismo formato débil `W/"…"`.
4. **Los middlewares son ASGI puro.** Los cinco `BaseHTTPMiddleware` se sustituyen
   —correlation id, access log y coste se funden en `ObservabilityMiddleware`—
   con el mismo orden y las mismas cabeceras.
5. **Una consulta cancelada por `statement_timeout` es un 503 de tipo
   `query-timeout`** (`api/errors.py`), que el navegador no reintenta
   (`web/src/lib/query-feedback.ts`). Las rutas de `/analytics` y
   `/competitive` pueden bajar el techo de sentencia para toda la petición
   (`API_ANALYTICS_STATEMENT_TIMEOUT_MS`, apagado por defecto hasta medir en
   producción); los jobs de precálculo nunca lo heredan, porque va en el
   contexto de la petición y no en las funciones de `db/repositories/`.

## Consecuencias

- Al desplegar, producción pasa a contar la cuota en Redis sin tocar su
  configuración. Los contadores empiezan de cero en el cambio. Para volver a la
  BD sin desplegar basta `RATE_LIMIT_BACKEND=db`. Los logs
  `ratelimit_redis_connected` / `ratelimit_redis_unavailable` dicen cuál se usa.
- Todas las ETags cambian una vez al desplegar: los clientes pierden un 304 y
  vuelven a revalidar con normalidad.
- En Redis, una petición denegada ya no consume cuota (igual que en la BD):
  antes cada 429 alargaba la ventana del propio cliente.
- Una excepción a mitad de un stream corta la conexión en vez de cerrar un
  cuerpo truncado como si hubiera terminado bien.
- El test estructural `tests/test_async_handlers_no_blocking_io.py` cubre ahora
  los subpaquetes de `api/routes/` y los wrappers de `shared/cache.py`.

## Alternativas descartadas

- **Mantener `db` por defecto y documentar que se fije `redis`.** Es lo que
  decía ADR-006, y el resultado fue que producción nunca lo fijó: el valor por
  defecto es el que gobierna.
- **Más workers de uvicorn.** Con una vCPU no añaden capacidad de cálculo, y
  multiplican las conexiones de los pools; el problema era el bloqueo del loop,
  no el número de procesos.
