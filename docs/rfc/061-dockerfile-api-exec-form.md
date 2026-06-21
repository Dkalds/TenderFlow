---
rfc: 061
title: "Dockerfile.api CMD: exec form para propagación correcta de señales"
issue: https://github.com/Dkalds/Licitaciones_sap_SP/issues/61
author: agent:architect
date: 2026-05-24
status: implemented
---

## Contexto

`Dockerfile.api` línea 60 usa shell form (`CMD ["sh", "-c", "..."]`), lo que ejecuta `sh` como PID 1. `sh` no propaga SIGTERM a procesos hijos, causando shutdown no-graceful: Docker espera 10s y envía SIGKILL, perdiendo requests en vuelo.

`Dockerfile.dashboard` ya usa exec form correctamente (líneas 60-67).

## Decisión

Cambiar CMD a exec form con `ENTRYPOINT` script que use `exec` para reemplazar el shell como PID 1, permitiendo expansión de `${FORWARDED_ALLOW_IPS}`.

**Opción elegida**: Usar `ENTRYPOINT` con un shell script inline que haga `exec python -m uvicorn ...`, de modo que uvicorn sea PID 1 tras el exec. Alternativamente, dado que `FORWARDED_ALLOW_IPS` tiene un default en ENV, podemos hardcodear el default en exec form y dejar que el usuario override con `--env` en docker run.

**Solución concreta**: Cambiar la línea CMD a exec form pura. Para la variable `FORWARDED_ALLOW_IPS`, usamos un script entrypoint mínimo con `exec`:

```dockerfile
COPY --chown=appuser:appuser docker-entrypoint-api.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint-api.sh
ENTRYPOINT ["docker-entrypoint-api.sh"]
CMD ["--workers", "2"]
```

Donde `docker-entrypoint-api.sh`:
```bash
#!/bin/sh
exec python -m uvicorn api.app:app \
    --host 0.0.0.0 \
    --port 8080 \
    --proxy-headers \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS}" \
    "$@"
```

Esto permite: (1) `exec` reemplaza sh como PID 1, (2) expansión de env vars, (3) CMD args se pasan como extra args.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Exec form pura sin entrypoint | Simple, una línea | No permite expansión de `${FORWARDED_ALLOW_IPS}` | Pierde configurabilidad |
| `tini` como init | Propaga señales correctamente | Añade dependencia externa | Overengineering para este caso |
| `CMD ["sh", "-c", "exec python -m uvicorn ..."]` | Mínimo cambio, una línea | Sigue usando sh (aunque exec lo reemplaza) | Menos idiomático que entrypoint |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Ninguno | — |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno | — |
| §3.4 Auto-marking tests | Ninguno | — |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. Crear `docker-entrypoint-api.sh` en raíz del proyecto
2. Modificar `Dockerfile.api` líneas 55-60: añadir COPY del entrypoint, ENTRYPOINT y CMD
3. Verificar que tests existentes no se rompen

**Archivos de partida**: `Dockerfile.api`, `Dockerfile.dashboard` (referencia)
**Riesgo estimado**: bajo
**Tiempo estimado**: <1 hora

## Acceptance criteria

- [ ] `docker-entrypoint-api.sh` existe con `exec` y expansión de `FORWARDED_ALLOW_IPS`
- [ ] `Dockerfile.api` usa ENTRYPOINT + CMD exec form
- [ ] uvicorn será PID 1 en el contenedor (via `exec`)
- [ ] `make lint && make typecheck && make test-unit` pasan en verde

## Notas de review

2026-05-24T00:00Z agent:reviewer — RFC aprobado. Cambio infraestructural sin impacto en código Python. Invariantes §3 no afectados. Riesgo bajo.
