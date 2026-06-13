# Seguridad y rotación de credenciales

Este documento centraliza las prácticas de seguridad del proyecto. La mayoría
de las defensas están verificadas por tests automatizados (ver
`tests/test_security.py`). Aquí registramos las que requieren acción humana
periódica.

## Secretos gestionados

| Variable                   | Alcance                           | Rotación | Responsable | Dónde vive                  |
|----------------------------|-----------------------------------|----------|-------------|-----------------------------|
| `TURSO_AUTH_TOKEN`         | Acceso a la BD remota Turso       | 90 días  | Maintainer  | GitHub Secrets + `.env`     |
| `TURSO_DATABASE_URL`       | URL libSQL de la BD remota        | Al migrar| Maintainer  | GitHub Secrets + `.env`     |
| `ALERT_EMAIL_TO`           | Destinatario de alertas por email | Al cambiar cuenta    | Maintainer | GitHub Secrets + `.env` |
| `ALERT_SMTP_USER`          | Cuenta remitente Gmail            | Al cambiar cuenta    | Maintainer | GitHub Secrets + `.env` |
| `ALERT_SMTP_PASSWORD`      | App Password de Gmail (16 chars)  | 90 días              | Maintainer | GitHub Secrets + `.env` |

## Procedimiento de rotación

### Turso (`TURSO_AUTH_TOKEN`)

1. Crear token nuevo: `turso db tokens create <db-name> --expiration 90d`.
2. Actualizar `TURSO_AUTH_TOKEN` en **GitHub → Settings → Secrets → Actions**.
3. Actualizar el `.env` local de cada maintainer.
4. Ejecutar `python -m scheduler.healthcheck` para verificar conectividad.
5. Revocar el token viejo: `turso db tokens invalidate <db-name> <old-token>`.

## Workflow de recordatorio automatizado

El workflow `.github/workflows/security.yml` lanza un job `secrets-rotation-reminder`
cada lunes a las 05:00 UTC que emite un aviso vía `::notice` en la ejecución de
Actions. Comprueba la fecha actual y emite alerta para que un maintainer actualice
los secretos cuando lleven más de 90 días.

## Defensas automatizadas (reforzadas en CI)

- **Pre-commit hooks** (`.pre-commit-config.yaml`): ruff, mypy, `detect-secrets`,
  `detect-private-key`, `check-added-large-files` (>1MB).
- **SAST Semgrep**: `p/ci`, `p/python`, `p/security-audit`, `p/owasp-top-ten`
  en cada push/PR y cada lunes.
- **`detect-secrets` en CI** con baseline `.secrets.baseline`; falla si hay
  nuevos hallazgos no auditados.
- **`pip-audit`** contra CVEs conocidas en dependencias.
- **Dependabot** (semanal) para actualizaciones de seguridad.
- **SARIF upload** de Semgrep a GitHub Security tab.

## Protección de endpoints

- Frontend web: rate-limit progresivo (2ⁿ backoff) tras 3 intentos
  fallidos y sesiones con caducidad limitada.
- SQL: todas las queries usan parámetros posicionales. Los nombres de columna se
  validan contra regex `^[a-zA-Z_]\w*$` antes de usarse en `ALTER TABLE`.
- XML: lxml con `resolve_entities=False`, `no_network=True` para prevenir XXE.

## Reporte de vulnerabilidades

Abrir un issue **privado** (Security advisory) en GitHub con etiqueta
`security`. No divulgar públicamente antes del parche. Respuesta en 72h.
