# Seguridad y rotación de credenciales

Este documento centraliza las prácticas de seguridad del proyecto. La mayoría
de las defensas están verificadas por tests automatizados (ver
`tests/test_config_settings.py`). Aquí registramos las que requieren acción humana
periódica.

## Secretos gestionados

| Variable                   | Alcance                           | Rotación | Responsable | Dónde vive                  |
|----------------------------|-----------------------------------|----------|-------------|-----------------------------|
| `DATABASE_URL`             | Credenciales Postgres/Supabase (user:pass embebidos) | Tras cutover + 90 días | Maintainer | GitHub Secrets + Render env + `.env` |
| `DATABASE_SSL_ROOT_CERT`   | Ruta a la CA de Supabase (cert público, no secreto)  | Al rotar CA Supabase   | Maintainer | Repo/volumen |
| `BACKUP_ENCRYPTION_KEY`    | Passphrase para cifrar dumps de `pg_dump` (backup.yml) | 180 días | Maintainer | GitHub Secrets |
| `ALERT_EMAIL_TO`           | Destinatario de alertas por email | Al cambiar cuenta    | Maintainer | GitHub Secrets + `.env` |
| `ALERT_SMTP_USER`          | Cuenta remitente Gmail            | Al cambiar cuenta    | Maintainer | GitHub Secrets + `.env` |
| `ALERT_SMTP_PASSWORD`      | App Password de Gmail (16 chars)  | 90 días              | Maintainer | GitHub Secrets + `.env` |

Turso/libSQL se retiró como backend (ADR-020, 2026-07-26); `TURSO_AUTH_TOKEN`
y `TURSO_DATABASE_URL` ya no existen como secretos gestionados.

## Procedimiento de rotación

### Controles nuevos (2026-07-26)

- Configurar `AUDIT_HMAC_KEY` con al menos 32 caracteres, diferente de las claves de sesión/API. El proceso API (`APP_PROFILE=api`) no arranca en producción sin ella; scraper/worker no la usan (`db/audit.py` solo lo llama código del servidor HTTP) y no la exigen.
- Configurar `AWS_ROLE_TO_ASSUME` y la trust policy OIDC de GitHub para el bucket de backups; el workflow ya no usa claves AWS estáticas.
- Configurar `WEBHOOK_ALLOWED_HOSTS` como lista explícita de dominios aprobados. Sin esa lista, los webhooks salientes quedan deshabilitados en producción.
- Mantener `DOCUMENT_ALLOWED_HOSTS` limitado a fuentes de contratación aprobadas. Las conexiones HTTP salientes fijan la IP validada, verifican TLS/SNI y rechazan redireccionamientos.
- Configurar `BACKUP_ENCRYPTION_KEY` antes de ejecutar cualquier copia: los scripts cifran todas las copias con GPG/AES-256 y exigen la misma clave para restaurarlas.
- Asociar o rotar las API keys heredadas sin `user_id`: producción y staging las rechazan para evitar que una clave sin propietario pueda actuar como administrador.
- Conservar `DOCUMENT_EXTRACTION_TIMEOUT_SECONDS` positivo en producción: cada extracción de PDF corre en un proceso aislado y se termina al exceder ese presupuesto.
- Ejecutar `python scripts/verify_audit_chain.py` en el runbook de incidentes (verifica la BD de `DATABASE_URL`; `--db-path` se retiró con SQLite, ADR-021). La verificación requiere recorrer la cadena completa; `--limit` ya no es válido porque ocultaría roturas o borrados.

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
- **Funciones SECURITY DEFINER cerradas** (`v59`): revocado `EXECUTE` a
  `PUBLIC` sobre `public.rls_auto_enable()` y sobre futuras funciones de
  `public`, evitando que una función de administración de RLS sea invocable
  desde roles no confiables.
- **Data API desactivada**: confirmar en Supabase Dashboard → Settings → API que la
  Data API está deshabilitada (defensa primaria; la RLS es la de profundidad).
- **Timeouts de pool**: `statement_timeout` / `idle_in_transaction_session_timeout`
  server-side en cada conexión (evitan DoS por agotamiento del pool).
- **Redacción de DSN**: la password de `DATABASE_URL` se redacta en logs y en las
  rutas de error de conexión (`observability.logging.redact_dsn`).

**Cutover pendiente, requiere coordinación con Supabase:** el script
`scripts/setup_pg_roles.sql` ya prepara `tenderflow_app` con solo DML,
`NOINHERIT`, `NOBYPASSRLS` y sin `CREATE` en `public`; las políticas RLS
explícitas están incluidas. Falta ejecutarlo con el rol administrador, guardar
`DATABASE_ADMIN_URL` solo para Alembic y cambiar el runtime a ese rol. Ver
`docs/runbooks/migracion-persistencia.md`.

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

### Acceso OAuth dinámico

`OAUTH_ALLOWED_EMAILS`/`OAUTH_ALLOWED_DOMAINS` siguen siendo el bootstrap
estático. `access_grants` añade concesiones de email o dominio administrables
desde el producto. El callback exige una coincidencia estática o dinámica; una
tabla vacía o una caída de Postgres deniega el acceso fuera de desarrollo. Las
altas y bajas requieren admin y dejan eventos de auditoría sin copiar el email
o dominio al audit log.

### Recuperación de contraseña local

`POST /auth/password-reset/request` no revela si existe la cuenta. Un token
aleatorio se envía en el fragmento `#token=` —no viaja a servidores ni access
logs— y en Postgres sólo se guarda su SHA-256. Caduca en 30 minutos, se consume
una vez y la confirmación revoca todas las sesiones activas. Las solicitudes se
limitan por IP y por hash del email; los tokens usados/expirados se purgan por
retención.

## Reporte de vulnerabilidades

Abrir un issue **privado** (Security advisory) en GitHub con etiqueta
`security`. No divulgar públicamente antes del parche. Respuesta en 72h.
