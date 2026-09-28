# Discussion Log — Issue #57: CSRF tokens para sesiones del dashboard

## Timeline

- **2026-05-24** — Issue creado: dashboard usa cookies de sesión sin protección CSRF.
- **2026-05-24** — RFC `docs/rfc/057-csrf-tokens-dashboard.md` creado y aprobado.
- **2026-05-24** — Implementación: `shared/csrf.py` con `generate_csrf_token()` y `validate_csrf_token()`.
- **2026-05-24** — Tests: 14 unit tests en `tests/test_unit_csrf.py`, todos passing.

## Decisiones clave

1. **Reutilizar `shared/signing.py`** en lugar de implementar HMAC desde cero — aprovecha rotación de claves existente.
2. **Token stateless** vinculado a session_id via hash — no requiere almacenamiento adicional en DB.
3. **No integrar en dashboard aún** — este issue crea la primitiva; la integración en formularios/middleware es un issue separado.

## Review notes

### Reviewer
- Código limpio, typing strict, sin `Any` ni `# type: ignore`.
- Reutiliza `shared/signing.sign/verify` correctamente.
- Token format bien diseñado: session binding + timestamp + HMAC.
- Tests cubren: valid token, wrong session, expired, tampered sig, tampered timestamp, empty inputs, malformed.

### Security triage
- **Severidad**: N/A (este cambio añade seguridad, no introduce vulnerabilidades).
- HMAC-SHA256 via `shared/signing.py` es criptográficamente sólido.
- `hmac.compare_digest` usado internamente por signing.py previene timing attacks.
- Session hash truncado a 16 chars (64 bits) — suficiente para binding, no leakea session token.
- Max age default 1h es razonable para CSRF tokens.

## Pendiente

- Integrar CSRF validation en middleware/formularios del dashboard (issue separado).
