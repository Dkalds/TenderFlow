#!/bin/sh
# Entrypoint for Dockerfile.api — exec ensures uvicorn is PID 1
# so SIGTERM/SIGINT propagate correctly for graceful shutdown.
# Render (and other PaaS) inject $PORT; fall back to 8080 for local Docker.
# Force single-process mode: Render auto-sets WEB_CONCURRENCY=1 which
# enables multiprocess supervisor and swallows child tracebacks on crash.
export WEB_CONCURRENCY=0
# El fallback de FORWARDED_ALLOW_IPS es loopback, nunca "*": con el comodín
# uvicorn reescribe la IP del cliente con el X-Forwarded-For de cualquier peer,
# que el propio cliente controla. Un despliegue tras proxy debe pasar el rango
# real del proxy por entorno; olvidarlo degrada a "no confío en nadie", no a
# "confío en todos".
# --limit-concurrency: por encima de ese número de conexiones abiertas (las
# keep-alive ociosas cuentan) o de tareas, uvicorn responde 503 a todo lo demás.
# Con 20 bastaba una decena de pestañas del dashboard —cada una mantiene su SSE
# de /licitaciones/stream hasta 5 min— y una ráfaga de carga para devolver 503,
# que el navegador reintenta con backoff y se percibe como lentitud. Lo que
# protege de verdad al proceso son el threadpool (API_THREADPOOL_TOKENS) y los
# pools de BD, así que este techo solo tiene que cortar un abuso real.
exec python -m uvicorn api.app:app \
    --host 0.0.0.0 \
    --port "${PORT:-8080}" \
    --proxy-headers \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
    --limit-concurrency "${UVICORN_LIMIT_CONCURRENCY:-200}" \
    --backlog "${UVICORN_BACKLOG:-64}" \
    --timeout-keep-alive "${UVICORN_KEEPALIVE:-5}" \
    "$@"
