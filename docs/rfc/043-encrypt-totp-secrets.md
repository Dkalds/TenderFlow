---
rfc: 043
title: Cifrar secretos TOTP almacenados en texto plano
issue: https://github.com/Dkalds/Licitaciones_sap_SP/issues/43
author: agent:architect
date: 2026-05-24
status: approved
---

## Contexto

Los secretos TOTP se almacenan sin cifrar en la tabla `totp_secrets`. Si la BD es comprometida, un atacante puede generar códigos TOTP válidos para todos los usuarios, anulando la 2FA. Los recovery codes SÍ están hasheados con argon2 (línea 127 de `db/totp.py`), pero el secreto TOTP principal no — una inconsistencia de seguridad crítica.

A diferencia de los recovery codes (que se pueden hashear porque solo se verifican), los secretos TOTP deben ser **reversibles** (se necesitan para generar/verificar códigos), por lo que requieren **cifrado simétrico**, no hashing.

## Decisión

1. Crear `shared/crypto.py` con funciones `encrypt_totp_secret()` / `decrypt_totp_secret()` usando **Fernet** (AES-128-CBC + HMAC-SHA256, de la librería `cryptography`).
2. Agregar `TOTP_ENCRYPTION_KEY` a `config/settings.py` como `SecretStr`. En dev se genera una clave efímera con warning; en prod es obligatoria.
3. Modificar `db/totp.py`:
   - `save_totp_secret()` cifra antes de guardar.
   - `get_totp_secret()` descifra al leer.
4. **NO** crear migración Alembic en este PR (requiere OK humano per §6). Se documenta como paso pendiente.
5. **Dependencia nueva**: `cryptography` — requiere OK humano per §6. Se implementa el código asumiendo que será aprobada.

### Qué NO se hace

- No se migran secretos existentes (requiere migración Alembic → humano).
- No se cambia el schema de la tabla (el campo `secret` sigue siendo TEXT, ahora almacena el ciphertext base64).
- No se toca `shared/auth_core.py`.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| AES-256-GCM directo (hazmat) | Más control, AES-256 | Más código, fácil equivocarse con nonces | Fernet es más seguro por defecto |
| NaCl/libsodium (PyNaCl) | Excelente API | Dependencia adicional no presente | Fernet ya viene con `cryptography` |
| XOR con HMAC-SHA256 (stdlib) | Sin deps | Rolling own crypto, inseguro | Inaceptable para producción |
| Hashear TOTP secrets | Sin deps | Imposible verificar códigos TOTP | TOTP requiere el secret original |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | `shared/crypto.py` nuevo módulo en área strict | Typing completo desde el inicio |
| §3.2 Upsert idempotente | Sin cambio — upsert sigue igual, solo cambia el valor | — |
| §3.3 Migraciones append-only | No se crea migración en este PR | Documentado como pendiente |
| §3.4 Auto-marking tests | Tests nombrados `test_unit_*` → auto-marked unit | — |
| §3.5 Pydantic v2 DTOs | Sin cambio | — |
| §3.6 HMAC/argon2 auth | Se añade Fernet (no reemplaza HMAC/argon2) | Complementario, no sustitutivo |

## Plan de implementación

1. Crear `shared/crypto.py` — `encrypt_totp_secret(secret) -> str`, `decrypt_totp_secret(token) -> str`
2. Agregar `TOTP_ENCRYPTION_KEY: SecretStr` a `config/settings.py` con fallback dev
3. Modificar `db/totp.py` — cifrar en `save_totp_secret`, descifrar en `get_totp_secret`
4. Escribir tests unitarios en `tests/test_unit_crypto.py`
5. Actualizar tests existentes en `tests/test_totp.py`

**Archivos de partida**: `db/totp.py`, `config/settings.py`, `shared/signing.py` (patrón de referencia)
**Riesgo estimado**: medio (dependencia nueva, cambio en flujo de datos sensibles)
**Tiempo estimado**: 2 horas

## Acceptance criteria

- [ ] `shared/crypto.py` cifra y descifra correctamente con Fernet
- [ ] Secretos TOTP se almacenan cifrados en BD
- [ ] `get_totp_secret()` devuelve el secreto descifrado (transparente para callers)
- [ ] Clave efímera en dev con warning, obligatoria en prod
- [ ] `make lint && make typecheck && make test-unit` pasan en verde
- [ ] diff-cover ≥ 80% en líneas nuevas

## Notas de review

2026-05-24T00:00Z agent:reviewer — RFC aprobado. Fernet es la elección correcta para cifrado simétrico de secretos cortos. La decisión de no crear migración Alembic sin OK humano es correcta per §6. Nota: `cryptography` como dependencia nueva requiere aprobación humana — el código se implementa pero el PR debe documentar este requisito.
