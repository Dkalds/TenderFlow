#!/bin/sh
# Entrypoint for Dockerfile.api — exec ensures uvicorn is PID 1
# so SIGTERM/SIGINT propagate correctly for graceful shutdown.
exec python -m uvicorn api.app:app \
    --host 0.0.0.0 \
    --port 8080 \
    --proxy-headers \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS}" \
    "$@"
