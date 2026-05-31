#!/bin/sh
# Entrypoint for Dockerfile.api — exec ensures uvicorn is PID 1
# so SIGTERM/SIGINT propagate correctly for graceful shutdown.
# Render (and other PaaS) inject $PORT; fall back to 8080 for local Docker.
# Unset WEB_CONCURRENCY to prevent uvicorn multiprocess supervisor:
# Render auto-sets WEB_CONCURRENCY=1, which spawns parent+child processes.
# The first child often dies on startup and the parent keeps retrying,
# confusing Render's port-detection. Single-process mode is fine for free tier.
unset WEB_CONCURRENCY
exec python -m uvicorn api.app:app \
    --host 0.0.0.0 \
    --port "${PORT:-8080}" \
    --proxy-headers \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
    "$@"
