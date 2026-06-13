---
rfc: 057
title: Implementar CSRF tokens para sesiones del dashboard
issue: https://github.com/Dkalds/Licitaciones_sap_SP/issues/57
author: agent:architect
date: 2026-05-24
status: obsolete
---

> Obsoleto: este RFC describe CSRF para el dashboard Streamlit eliminado y se conserva solo como referencia histórica.


## Contexto

AGENTS.md §3.6 lista "HMAC-signed CSRF" como invariante, pero no existe implementación de CSRF tokens. El dashboard usa cookies de sesión (`db/sessions.py`), lo que lo hace vulnerable a CSRF en requests POST/PUT/DELETE. La API REST usa `X-API-Key` en headers (implícitamente protegida).

## Decisión

Crear `shared/csrf.py` con generación y validación de tokens CSRF firmados con HMAC usando `shared/signing.py`. El token incluye session_id + timestamp para binding a sesión y protección contra replay.

**Qué se hace:**
1. Nuevo módulo `shared/csrf.py` con `generate_csrf_token()` y `validate_csrf_token()`
2. Tokens firmados via `shared/signing.sign()` / `shared/signing.verify()` (reutiliza rotación de claves)
3. Token format: `{session_id_hash}:{timestamp}:{signature}` donde signature = HMAC(session_id_hash:timestamp)
4. Max age configurable (default 1h)

**Qué NO se hace:**
- No se modifica `shared/auth_core.py`
- No se integra en el dashboard (eso es un issue separado de wiring)
- No se modifica `db/sessions.py`
- No se tocan migraciones

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Double-submit cookie | Simple, stateless | No vinculado a sesión, vulnerable a subdomain attacks | Menor seguridad |
| Synchronizer token (DB) | Estándar OWASP | Requiere migración DB, más complejidad | Innecesario con HMAC |
| HMAC-signed token (elegida) | Stateless, vinculado a sesión, usa infra existente | — | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Nuevo módulo en shared/ — debe ser strict | Typing completo desde el inicio |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno | — |
| §3.4 Auto-marking tests | Ninguno | Test nombrado test_unit_csrf.py |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Cumple el invariante | Usa shared/signing.py existente |

## Plan de implementación

1. Crear `shared/csrf.py` con `generate_csrf_token()` y `validate_csrf_token()`
2. Crear `tests/test_unit_csrf.py` con tests unitarios

**Archivos de partida**: `shared/signing.py`, `db/sessions.py`
**Riesgo estimado**: bajo
**Tiempo estimado**: 1 hora

## Acceptance criteria

- [x] `shared/csrf.py` genera tokens HMAC-signed vinculados a session_id
- [x] `validate_csrf_token()` verifica firma, session binding y max_age
- [x] Tokens expirados son rechazados
- [x] Tokens con session_id incorrecto son rechazados
- [x] Tokens manipulados son rechazados
- [x] `make lint && make typecheck && make test-unit` pasan en verde
- [x] diff-cover ≥ 80% en líneas nuevas

## Notas de review

2026-05-24T00:00Z agent:reviewer — RFC aprobado. Diseño correcto: reutiliza signing.py con rotación de claves, stateless, vinculado a sesión. No toca auth_core.py ni DB. Invariantes respetados.
