# Seguridad y rotación de credenciales

Este documento centraliza las prácticas de seguridad del proyecto. La mayoría
de las defensas están verificadas por tests automatizados (ver
`tests/test_config_settings.py`). Aquí registramos las que requieren acción humana
periódica.

## Secretos gestionados

| Variable                   | Alcance                           | Rotación | Responsable | Dónde vive                  |
|----------------------------|-----------------------------------|----------|-------------|-----------------------------|
| `DATABASE_URL`             | Credenciales Postgres/Supabase (user:pass embebidos) | Tras cutover + 90 días | Maintainer | GitHub Secrets + Render env + `.env` |
| `DATABASE_ADMIN_URL`       | DSN del rol DUEÑO del schema: el único con DDL y el único que bypassa la RLS de `v52` | 90 días | Maintainer | **Solo** GitHub Secrets (lo usa `migrate.yml`). Nunca en Render ni en el `.env` de la API |
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

**Cutover de roles: pendiente a 2026-09-06.** El script
`scripts/setup_pg_roles.sql` ya prepara `tenderflow_app` con solo DML,
`NOINHERIT`, `NOBYPASSRLS` y sin `CREATE` en `public`; las políticas RLS
explícitas están incluidas. Falta ejecutarlo con el rol administrador, guardar
`DATABASE_ADMIN_URL` solo para Alembic y cambiar el runtime a ese rol.

**El procedimiento completo, con sus dos controles de aceptación en comandos
copiables, está en `docs/runbooks/persistence-tripwires.md` (Partes 1 y 2).**

Lo que el repositorio ya deja preparado, para que el cutover no se pueda
deshacer por descuido:

- `config/settings.py::database_admin_url()` es la única vía de acceso a la
  credencial de administración, y solo la sirve con `APP_PROFILE=scraper` —el
  perfil de `migrate.yml`—: cualquier otro perfil, sin declarar o mal escrito,
  levanta (allowlist, no lista de prohibidos). No es campo de `Settings`: la API
  no tiene ni atributo que leer. Fijado por `tests/test_settings_admin_url.py`.
- `scripts/check_env_parity.py` falla si `DATABASE_ADMIN_URL` aparece en
  `render.yaml` — un servicio que atiende HTTP no puede llevarla en su entorno.
- `.github/workflows/migrate.yml` la usa y avisa en el resumen del run cuando
  cae al fallback de `DATABASE_URL`. El paso 10 del runbook convierte ese aviso
  en error una vez completado el cutover.

Alcance de lo que cierra: el DDL (la app deja de poder alterar el schema) y la
Data API de Supabase (`anon`/`authenticated` quedan en deny-all). **No** cierra
el aislamiento entre organizaciones, que sigue viviendo en la capa de
aplicación; el runbook explica por qué y qué haría falta para moverlo a RLS.

Contexto de la migración a Postgres: `docs/runbooks/migracion-persistencia.md`.

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

---

## Retención de datos

<!-- BEGIN retencion (generado por scripts/gen_retention_doc.py — no editar a mano) -->

Los plazos son configuración (`RETENTION_*` en `config/settings.py`, documentados en
`.env.example`) y la política vive en `scheduler/retention.py::POLITICA_RETENCION`.
Esta tabla se genera con `python scripts/gen_retention_doc.py`; CI la verifica con
`--check`, así que no puede quedarse atrás respecto del código que purga.

El job programado `retention_cleanup` la aplica a diario. Las tablas
`licitaciones` y `adjudicaciones` **no** se purgan: son el dato público que el
producto existe para conservar.

| Tabla | Plazo | Motivo | Comando |
|---|---|---|---|
| `extraction_runs` | 90 días (3 meses) | Diagnóstico de la ingesta. Pasado un trimestre, un run concreto ya no explica nada que la serie agregada no cuente mejor. | `python scripts/retention_cleanup.py --apply` |
| `audit_log` | 180 días (6 meses) | Trazabilidad de acciones de usuario para investigar un incidente. Encadenado por SHA-256: se purga por el extremo antiguo, nunca por el medio. | `python scripts/retention_cleanup.py --apply` |
| `failed_extractions` | 30 días (1 mes) | Cola de fallos. Solo se purgan los **resueltos**: un fallo abierto no caduca por tiempo. | `python scripts/retention_cleanup.py --apply` |
| `licitaciones_history` | 365 días (1 año) | Histórico de cambios de un expediente. Un año cubre el ciclo completo de licitación y adjudicación. | `python scripts/retention_cleanup.py --apply` |
| `access_log` | 180 días (6 meses) | Accesos a la plataforma. Dato personal: se conserva lo mínimo para investigar abuso y no más. | `python scripts/retention_cleanup.py --apply` |
| `idempotency_keys` | 1 día | Solo tienen que sobrevivir al reintento que las justifica. | `python scripts/retention_cleanup.py --apply` |
| `webhook_deliveries` | 90 días (3 meses) | Historial de entregas para depurar un webhook que falla. El reintento vive en horas, no en meses. | `python scripts/retention_cleanup.py --apply` |
| `solicitudes_acceso` | 720 días (24 meses) | **Plazo publicado en el aviso legal.** Cambiarlo cambia una promesa hecha al visitante en el momento de la recogida (RGPD art. 13). | `python scripts/retention_cleanup.py --apply` |
| `password_reset_tokens` | 7 días | Un token de recuperación caducado no sirve para nada y sí identifica a quien lo pidió. | `python scripts/retention_cleanup.py --apply` |
| `client_errors` | 30 días (1 mes) | Huella sin PII de un fallo de JavaScript. No hace falta guardarla más de lo que dura investigar una regresión. | `python scripts/retention_cleanup.py --apply` |
| `rate_limits` | 1 día | Ventanas de rate limit. Se purgan las **expiradas** en cada pasada, sin esperar al plazo: la columna que manda es `reset_at`. | `python scripts/retention_cleanup.py --apply` (por `reset_at`, no por plazo) |

<!-- END retencion -->

---

## Política de vulnerabilidades

Un aviso de seguridad sin plazo se queda abierto. Estos son los plazos, contados
desde que el aviso aparece en la pestaña de seguridad del repositorio:

| Severidad | Plazo máximo hasta el parche | Qué pasa si se agota |
|---|---|---|
| Crítica | 48 horas | Se para el trabajo en curso hasta cerrarlo. |
| Alta | 7 días naturales | Bloquea el merge de features nuevas en el área afectada. |
| Moderada | 30 días naturales | Entra en el backlog con fecha límite explícita. |
| Baja | Sin plazo fijo | Se agrupa con la siguiente actualización de dependencias. |

**Excepciones.** Un aviso que no aplica —la ruta vulnerable no se ejecuta, la
dependencia es de desarrollo y no viaja a producción— se **descarta con
motivo escrito** en el propio aviso. Descartar sin motivo no está permitido:
es indistinguible de ignorar.

**Avisos fantasma.** Un aviso contra un fichero de lock que ya no existe en el
árbol (por ejemplo el `uv.lock` retirado) no es un falso positivo del
escaneo: es un aviso sobre un artefacto que GitHub sigue viendo en el
historial. Se cierran en bloque, con una nota que diga cuál fue el fichero y
cuándo se retiró.

**Medición.** «Cero avisos altos abiertos más de siete días» se comprueba en la
pestaña de seguridad del repositorio y se anota con fecha. No hay comando que lo
derive del árbol: los avisos son estado de GitHub, no del repositorio.
