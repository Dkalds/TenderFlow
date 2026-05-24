# Discussion: Cifrar secretos TOTP at-rest

**Issue**: https://github.com/Dkalds/Licitaciones_sap_SP/issues/43
**RFC**: docs/rfc/043-encrypt-totp-secrets.md
**Date**: 2026-05-24

## Resumen

Los secretos TOTP se almacenaban en texto plano en `totp_secrets.secret`. Se implementó cifrado Fernet (AES-128-CBC + HMAC-SHA256) transparente en `shared/crypto.py`, con clave desde `TOTP_ENCRYPTION_KEY` env var.

## Decisiones tomadas

1. **Fernet sobre AES-256-GCM directo**: Fernet es más seguro por defecto (maneja IV, padding, MAC automáticamente). AES-256-GCM requiere gestión manual de nonces.
2. **Backward compatibility**: Detección heurística de Fernet prefix para leer secretos legacy sin cifrar.
3. **No migración Alembic**: Requiere OK humano. Los secretos legacy se leen sin cifrar hasta que se re-guarden.
4. **Dependencia `cryptography`**: Necesaria pero requiere aprobación humana para agregar a requirements.

## Pendientes

- [ ] Agregar `cryptography` a dependencias
- [ ] Migración Alembic para cifrar secretos existentes
- [ ] Runbook de rotación de `TOTP_ENCRYPTION_KEY`
- [ ] Considerar migración a AES-256-GCM si se necesita en el futuro
