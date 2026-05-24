---
rfc: 048
title: "Fix get_stored_hash silent exception swallowing enabling timing attacks"
issue: https://github.com/Dkalds/Licitaciones_sap_SP/issues/48
author: agent:architect
date: 2026-05-24
status: approved
---

## Contexto

`services/auth.py:get_stored_hash()` catches all exceptions and returns `None`. When `stored_hash` is `None` in `api/auth.py:127-129`, the `hmac.compare_digest` call is skipped entirely (due to the `if stored_hash and ...` guard), creating a measurable timing difference that reveals whether a key_id exists. Additionally, DB errors are silently swallowed, masking operational issues.

Related invariant: AGENTS.md §3.6 — HMAC-signed CSRF + argon2/bcrypt auth must not be weakened.

## Decisión

1. **`services/auth.py:get_stored_hash`**: Remove the bare `except Exception: return None`. Instead, log the error and re-raise. This makes DB failures visible and prevents them from being misinterpreted as "key not found".

2. **`api/auth.py:127-129`**: Wrap the `get_stored_hash` call in a try/except that catches DB errors and returns HTTP 503 (Service Unavailable) instead of 401. When `stored_hash` is `None` (key genuinely not found), perform a dummy `hmac.compare_digest` to maintain constant-time behavior before raising 401.

What we do NOT do:
- We do not change the hashing algorithm or auth flow.
- We do not modify `shared/auth_core.py`.
- We do not touch DB schema or migrations.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Return sentinel string instead of None | Simple | Still swallows errors, masks DB issues | Doesn't fix root cause |
| Retry on DB error | More resilient | Adds latency, complexity | Over-engineering for this fix |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Ninguno — services/auth.py not in strict list | — |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno | — |
| §3.4 Auto-marking tests | Ninguno | — |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Positive — fixes timing leak | Constant-time comparison preserved in all paths |

## Plan de implementación

1. `services/auth.py`: Remove bare except, log + re-raise DB errors in `get_stored_hash`
2. `api/auth.py`: Add try/except around `get_stored_hash` call — DB error → 503; None → dummy compare_digest + 401
3. `tests/test_unit_get_stored_hash.py`: Test that DB errors propagate, timing attack protection works

**Archivos de partida**: `services/auth.py`, `api/auth.py`
**Riesgo estimado**: bajo
**Tiempo estimado**: 1 hora

## Acceptance criteria

- [x] `get_stored_hash` re-raises DB exceptions after logging
- [x] `api/auth.py` returns 503 on DB error, not 401
- [x] Constant-time comparison happens even when stored_hash is None
- [x] `make lint && make typecheck && make test-unit` pasan en verde
- [x] diff-cover ≥ 80% en líneas nuevas

## Notas de review

2026-05-24T00:00Z agent:reviewer — RFC approved. Changes are minimal, security-positive, no invariants broken. Constant-time path for None case already exists at line 119 but the get_stored_hash path at line 128 lacks it — fix is correct.
