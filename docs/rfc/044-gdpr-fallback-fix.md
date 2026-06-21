---
rfc: 044
title: "GDPR get_user_id_from_key_id debe retornar None en lugar de fallback al primer usuario"
issue: https://github.com/Dkalds/Licitaciones_sap_SP/issues/44
author: agent:architect
date: 2026-05-24
status: implemented
---

## Contexto

`get_user_id_from_key_id()` en `services/gdpr.py` tiene dos ramas de fallback que ejecutan `SELECT id FROM users LIMIT 1` y retornan el primer usuario de la BD. Esto causa que operaciones GDPR (exportación, anonimización, revocación de sesiones) se ejecuten sobre el usuario equivocado cuando:

1. La columna `user_id` no existe en `api_keys`
2. La columna existe pero el valor es NULL para la key consultada

Esto viola RGPD Art. 17 (derecho al olvido) y Art. 20 (portabilidad).

## Decisión

1. Reemplazar ambos fallbacks `SELECT id FROM users LIMIT 1` por `return None` con log de warning.
2. Asegurar que los callers en `api/routes/me.py` manejan `None` correctamente (ya lo hacen con `if user_id:` guards, excepto `rotate_my_key` que pasa `user_id=None` a `create_api_key`).
3. Agregar tests que verifiquen que NUNCA se retorna un usuario arbitrario.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Hacer la columna user_id obligatoria (NOT NULL) | Elimina el problema de raíz | Requiere migración alembic, rompe backwards compat | Requiere OK humano para migración; se puede hacer después |
| Lanzar excepción en lugar de None | Falla ruidosa | Rompe endpoints que hoy toleran None | Demasiado disruptivo |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Ninguno — services/ no es strict | — |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno — no hay migración | — |
| §3.4 Auto-marking tests | Ninguno — test se llama test_unit_* | — |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. `services/gdpr.py` — reemplazar ambos fallbacks por `log.warning(...)` + `return None`
2. `api/routes/me.py` — verificar que `rotate_my_key` maneja `user_id=None` (actualmente lo pasa directo a `create_api_key`)
3. `tests/test_unit_gdpr_fallback.py` — tests que verifican que missing key y missing column retornan None, no un usuario arbitrario

**Archivos de partida**: `services/gdpr.py`, `api/routes/me.py`, `tests/test_gdpr.py`
**Riesgo estimado**: bajo
**Tiempo estimado**: 1 hora

## Acceptance criteria

- [x] `get_user_id_from_key_id` retorna `None` cuando `user_id` column no existe
- [x] `get_user_id_from_key_id` retorna `None` cuando `user_id` es NULL
- [x] Callers manejan `None` sin crash
- [x] Test unitario verifica que nunca se retorna un usuario arbitrario
- [x] `make lint && make typecheck && make test-unit` pasan en verde

## Notas de review

2026-05-24T00:00Z agent:reviewer — RFC aprobado. Cambio mínimo, bajo riesgo. Los callers existentes ya tienen guards `if user_id:` excepto `rotate_my_key` que necesita revisión.
