---
rfc: 062
title: "OAuth nonce store: fail-closed con fallback in-memory"
issue: https://github.com/Dkalds/Licitaciones_sap_SP/issues/62
author: agent:architect
date: 2026-05-24
status: implemented
---

## Contexto

`_RedisNonceStore.contains()` retorna `False` cuando Redis no está disponible (líneas 108-110 de `shared/auth_core.py`). Esto es fail-open: un nonce no se considera "visto", permitiendo replay attacks durante la ventana de indisponibilidad de Redis.

El issue #62 identifica esto como un riesgo de seguridad P3.

## Decisión

Implementar **Opción B del issue**: fail-closed con fallback a `_TTLCacheNonceStore` en memoria.

Cuando `_RedisNonceStore` detecta un error de Redis en `contains()` o `add()`:
1. Log warning (ya existe).
2. Delegar al fallback `_TTLCacheNonceStore` interno.
3. **No** retornar `False` directamente — el fallback in-memory provee protección anti-replay dentro del mismo proceso.

Esto no es perfecto en multi-proceso (cada worker tiene su propio fallback), pero es estrictamente mejor que fail-open y no bloquea el login (evita la fricción de Opción A).

**Qué NO se hace**: No se cambia a fail-closed puro (Opción A) porque bloquearía logins legítimos cuando Redis cae temporalmente.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| A: Fail-closed (rechazar login) | Máxima seguridad | Bloquea usuarios legítimos si Redis cae | Demasiado disruptivo para P3 |
| B: Fallback in-memory (elegida) | Seguridad razonable + disponibilidad | No cubre cross-process durante fallo Redis | Mejor trade-off |
| C: Solo alerting | Mínimo cambio | No mitiga el ataque | Insuficiente |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | shared/ es strict-in-progress | Mantener typing sin `Any` nuevo |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno | — |
| §3.4 Auto-marking tests | Ninguno | — |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Mejora seguridad del nonce store | — |

## Plan de implementación

1. Modificar `_RedisNonceStore.__init__` para crear un `_TTLCacheNonceStore` interno como fallback.
2. En `contains()`: on Redis error, delegar a `self._fallback.contains(nonce)`.
3. En `add()`: on Redis error, delegar a `self._fallback.add(nonce, ttl_seconds)`. También llamar al fallback en el happy path para tener datos locales si Redis cae después.
4. Actualizar tests: cambiar `test_redis_nonce_store_contains_fail_open` → verificar que fallback se usa.
5. Añadir test para verificar que el fallback funciona correctamente.

**Archivos de partida**: `shared/auth_core.py`, `tests/test_auth_core.py`
**Riesgo estimado**: bajo
**Tiempo estimado**: 1 hora

## Acceptance criteria

- [ ] `_RedisNonceStore.contains()` nunca retorna `False` por error de Redis — delega al fallback
- [ ] `_RedisNonceStore.add()` siempre escribe al fallback además de Redis
- [ ] Tests unitarios cubren el comportamiento de fallback
- [ ] `make lint && make typecheck && make test-unit` pasan en verde
- [ ] diff-cover ≥ 80% en líneas nuevas

## Notas de review

2026-05-24T00:00Z agent:reviewer — RFC aprobado. Cambio mínimo, bien acotado. El fallback dual (Redis + in-memory) es el patrón correcto para este caso.
