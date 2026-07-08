# Seguridad y rotación de credenciales

Este documento centraliza las prácticas de seguridad del proyecto. La mayoría
de las defensas están verificadas por tests automatizados (ver
`tests/test_security.py`). Aquí registramos las que requieren acción humana
periódica.

## Secretos gestionados

| Variable                   | Alcance                           | Rotación | Responsable | Dónde vive                  |
|----------------------------|-----------------------------------|----------|-------------|-----------------------------|
| `DATABASE_URL`             | Credenciales Postgres/Supabase (user:pass embebidos) | Tras cutover + 90 días | Maintainer | GitHub Secrets + Render env + `.env` |
| `DATABASE_SSL_ROOT_CERT`   | Ruta a la CA de Supabase (cert público, no secreto)  | Al rotar CA Supabase   | Maintainer | Repo/volumen |
| `BACKUP_ENCRYPTION_KEY`    | Passphrase para cifrar dumps de `pg_dump` (backup.yml) | 180 días | Maintainer | GitHub Secrets |
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

### Postgres / Supabase (`DATABASE_URL`)

La `DATABASE_URL` lleva la password del rol embebida y ha viajado por `.env`,
laptops, scripts ETL y GitHub/Render secrets durante la migración (ADR-016).
**Rotarla tras el cutover** y luego cada 90 días:

1. Supabase Dashboard → Project → Database → **Reset database password**.
2. Reconstruir la `DATABASE_URL` (Supavisor session pooler, puerto 5432) con
   `?sslmode=verify-full` y actualizarla en: **Render** (env var), **GitHub →
   Settings → Secrets → Actions**, y el `.env` local de cada maintainer.
3. `make doctor` (o `python scripts/doctor.py`) para verificar conectividad — el
   DSN se muestra enmascarado (solo host/puerto/db).
4. Reiniciar API/scheduler para que tomen la nueva credencial.

### Hardening de la integración Supabase

Defensas activas (revisión de seguridad 2026-07, ADR-016):

- **TLS verificado**: `config.settings` rechaza `sslmode=disable/allow/prefer` en
  prod/staging y recomienda `verify-full` + `DATABASE_SSL_ROOT_CERT` (CA de Supabase).
- **RLS defensiva** (`db/alembic/versions/v52_rls_lockdown.py`): RLS habilitada en
  todas las tablas de `public` + `REVOKE` a `anon`/`authenticated`, de modo que la
  Data API/PostgREST queda cerrada aunque se reactive (fail-closed).
- **Data API desactivada**: confirmar en Supabase Dashboard → Settings → API que la
  Data API está deshabilitada (defensa primaria; la RLS es la de profundidad).
- **Timeouts de pool**: `statement_timeout` / `idle_in_transaction_session_timeout`
  server-side en cada conexión (evitan DoS por agotamiento del pool).
- **Redacción de DSN**: la password de `DATABASE_URL` se redacta en logs y en las
  rutas de error de conexión (`observability.logging.redact_dsn`).

**Roadmap (pendiente, requiere coordinación con Supabase):** introducir un rol de
aplicación de privilegios mínimos (`tenderflow_app`, solo DML) separado de un rol
admin para migraciones (`DATABASE_ADMIN_URL`). ⚠️ Al hacerlo, como ese rol NO sería
dueño de las tablas, **la migración RLS v52 lo dejaría sin acceso**: hay que añadir
políticas RLS explícitas (o `GRANT` selectivos por tabla) para el rol app antes del
cutover. Ver `docs/runbooks/migracion-persistencia.md`.

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
