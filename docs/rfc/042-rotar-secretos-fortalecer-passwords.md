---
rfc: 042
title: Fortalecer validación de secretos y contraseñas en arranque
issue: https://github.com/Dkalds/Licitaciones_sap_SP/issues/42
author: agent:architect
date: 2026-05-24
status: implemented
---

## Contexto

El issue #42 reporta que `.env` contiene credenciales débiles (e.g. `Deloitte123456.`) y secretos que podrían haberse filtrado. Aunque `.env` está en `.gitignore` y nunca fue commiteado al historial git, el código no valida la fortaleza de los secretos al arrancar.

La rotación de secretos en sí es una acción operativa que requiere intervención humana (rotar tokens en Turso, Gmail, Google OAuth, etc.). Lo que el código puede hacer es **rechazar secretos débiles al arrancar** y **mejorar la redacción de secretos en logs**.

## Decisión

### Qué se hace:

1. **`config/settings.py`**: Añadir validadores que en `ENV=prod|staging`:
   - Rechacen `DASHBOARD_PASSWORD` en texto plano si se configura sin hash (ya existe parcialmente)
   - Validen longitud mínima de `SIGNING_KEY` (≥32 chars)
   - Validen longitud mínima de `TURSO_AUTH_TOKEN` (≥20 chars, es un JWT)
   - Validen que `ALERT_SMTP_PASSWORD` no esté vacío si `ALERT_EMAIL_TO` está configurado
   - Rechacen contraseñas que contengan patrones débiles conocidos (nombre de empresa, secuencias numéricas simples)
   - Validen `GF_SECURITY_ADMIN_PASSWORD` mínimo 16 chars si está configurado

2. **`config/settings.py`**: Añadir campo `GF_SECURITY_ADMIN_PASSWORD: SecretStr` para que pase por validación

3. **`observability/logging.py`**: Añadir a `_SENSITIVE_ENV_VARS`: `API_HMAC_SECRET`, `SIGNING_KEY`, `REDIS_PASSWORD`, `GF_SECURITY_ADMIN_PASSWORD`

4. **`shared/password_policy.py`** (nuevo): Módulo con función `check_password_strength()` reutilizable por `scripts/hash_password.py` y validadores de settings

5. **`scripts/hash_password.py`**: Integrar `check_password_strength()` para advertir sobre contraseñas débiles

### Qué NO se hace:

- No se modifican `.env` ni `.env.example` (path_denylist del coder + requiere OK humano §6)
- No se rotan secretos (acción operativa manual)
- No se modifican workflows CI/CD
- No se tocan migraciones alembic

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Solo documentar en runbook | Cero riesgo de romper | No previene reincidencia | Insuficiente para P0 |
| Integrar vault/secrets manager | Solución definitiva | Requiere infra nueva, fuera de scope | Futuro, no urgente |
| Validar solo en CI | Catch temprano | No protege runtime | Complementario, no suficiente |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Afecta `config/settings.py`, `shared/` | Mantener strict, nuevos campos tipados |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno | — |
| §3.4 Auto-marking tests | Ninguno | Tests nombrados `test_unit_*` |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Fortalece, no debilita | — |

## Plan de implementación

1. Crear `shared/password_policy.py` con `check_password_strength()`
2. Añadir campo `GF_SECURITY_ADMIN_PASSWORD` y validadores en `config/settings.py`
3. Añadir secretos faltantes a `observability/logging.py` redaction list
4. Integrar policy check en `scripts/hash_password.py`
5. Escribir tests unitarios

**Archivos de partida**: `config/settings.py`, `observability/logging.py`, `scripts/hash_password.py`, `shared/auth_core.py`
**Riesgo estimado**: bajo
**Tiempo estimado**: 2 horas

## Acceptance criteria

- [ ] `Settings(ENV="prod", DASHBOARD_PASSWORD="Deloitte123456.", ...)` falla con error claro
- [ ] Secretos cortos (<32 chars) son rechazados en prod para SIGNING_KEY, API_HMAC_SECRET
- [ ] `_SENSITIVE_ENV_VARS` incluye todos los secretos del proyecto
- [ ] `check_password_strength()` detecta patrones débiles
- [ ] `make lint && make typecheck && make test-unit` pasan en verde
- [ ] diff-cover ≥ 80% en líneas nuevas

## Notas de review

2026-05-24T00:00Z agent:reviewer — RFC aprobado. No toca denylist paths. Fortalece §3.6 sin debilitar. Validadores son fail-fast en arranque, no afectan runtime. Nuevo módulo `shared/password_policy.py` está en área strict — asegurar typing completo.
