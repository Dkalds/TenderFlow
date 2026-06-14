#!/bin/sh
# Entrypoint for Dockerfile.api — exec ensures uvicorn is PID 1
# so SIGTERM/SIGINT propagate correctly for graceful shutdown.
# Render (and other PaaS) inject $PORT; fall back to 8080 for local Docker.
# Force single-process mode: Render auto-sets WEB_CONCURRENCY=1 which
# enables multiprocess supervisor and swallows child tracebacks on crash.
export WEB_CONCURRENCY=0
exec python -m uvicorn api.app:app \
    --host 0.0.0.0 \
    --port "${PORT:-8080}" \
    --proxy-headers \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
    --limit-concurrency "${UVICORN_LIMIT_CONCURRENCY:-20}" \
    --backlog "${UVICORN_BACKLOG:-64}" \
    --timeout-keep-alive "${UVICORN_KEEPALIVE:-5}" \
    "$@"
