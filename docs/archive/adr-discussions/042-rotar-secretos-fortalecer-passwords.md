# Discussion: #42 — Rotar secretos expuestos y fortalecer contraseñas

**Issue**: https://github.com/Dkalds/Licitaciones_sap_SP/issues/42
**RFC**: `docs/rfc/042-rotar-secretos-fortalecer-passwords.md`
**Date**: 2026-05-24

## Decisiones tomadas

1. **Scope limitado a código**: La rotación de secretos es operativa y requiere acción humana. El código ahora **rechaza secretos débiles al arrancar** en `ENV=prod|staging`.

2. **Nuevo módulo `shared/password_policy.py`**: Centraliza la lógica de validación de fortaleza, reutilizable por settings y scripts.

3. **Validadores añadidos en `config/settings.py`**:
   - `DASHBOARD_PASSWORD` rechazada si contiene patrones débiles (Deloitte, password, 123456, etc.)
   - `GF_SECURITY_ADMIN_PASSWORD` (nuevo campo) validado con misma política
   - `SIGNING_KEY` requiere ≥32 chars en prod
   - `ALERT_SMTP_PASSWORD` obligatorio si `ALERT_EMAIL_TO` está configurado

4. **Redacción de secretos ampliada** en `observability/logging.py`: añadidos `API_HMAC_SECRET`, `SIGNING_KEY`, `REDIS_PASSWORD`, `GF_SECURITY_ADMIN_PASSWORD`, `DASHBOARD_PASSWORD_HASH`.

5. **No se modificaron** `.env`, `.env.example`, workflows, ni migraciones (path_denylist + §6 AGENTS.md).

## Acciones pendientes (requieren humano)

- [ ] Rotar `TURSO_AUTH_TOKEN` en consola Turso
- [ ] Rotar `GOOGLE_CLIENT_SECRET` en Google Cloud Console
- [ ] Rotar `API_HMAC_SECRET` y `SIGNING_KEY` (regenerar con `secrets.token_hex(32)`)
- [ ] Cambiar `DASHBOARD_PASSWORD` por una contraseña fuerte y generar hash con `scripts/hash_password.py`
- [ ] Cambiar `GF_SECURITY_ADMIN_PASSWORD` por una contraseña fuerte
- [ ] Rotar `ALERT_SMTP_PASSWORD` (app password de Gmail)
- [ ] Actualizar `.env` con los nuevos valores (no commitear)
