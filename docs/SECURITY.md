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
| `EMAIL_API_KEY`            | Clave del ESP (Resend / Postmark) cuando `EMAIL_BACKEND` no es `smtp`; sólo permiso de envío | 90 días | Maintainer | Render env (dashboard) + `.env`; si el healthcheck de GitHub Actions cambia de backend, también GitHub Secrets. Procedimiento en [runbooks/correo-transaccional.md](runbooks/correo-transaccional.md) |

Turso/libSQL se retiró como backend (ADR-020, 2026-07-26); `TURSO_AUTH_TOKEN`
y `TURSO_DATABASE_URL` ya no existen como secretos gestionados.

## Procedimiento de rotación

### Controles nuevos (2026-07-26)

- Configurar `AUDIT_HMAC_KEY` con al menos 32 caracteres, diferente de las claves de sesión/API. El proceso API (`APP_PROFILE=api`) no arranca en producción sin ella; scraper/worker no la usan (`db/audit.py` solo lo llama código del servidor HTTP) y no la exigen.
- Configurar `AWS_ROLE_TO_ASSUME` y la trust policy OIDC de GitHub para el bucket de backups; el workflow ya no usa claves AWS estáticas.
- Configurar `WEBHOOK_ALLOWED_HOSTS` como lista explícita de dominios aprobados. Sin esa lista, los webhooks salientes quedan deshabilitados en producción.
- Rotar el secret de un webhook con `POST /api/v1/webhooks/{id}/rotate-secret` en vez de borrarlo y recrearlo: conserva id e historial, invalida el anterior al instante (sin gracia) y queda en auditoría como `webhook.secret_rotated`. Las entregas llevan además `X-Webhook-Timestamp` y `X-Webhook-Signature-V2` para que el receptor rechace replays; receta en [integraciones/webhooks.md](integraciones/webhooks.md).
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
Data API de Supabase (`anon`/`authenticated` quedan en deny-all). El
aislamiento entre organizaciones es otra cosa: lo aplica la capa de aplicación
y, desde `v128`, lo respalda la RLS por tenant de la sección siguiente — que
solo se ejerce de verdad con un rol sin `BYPASSRLS`, es decir, tras el cutover.

Contexto de la migración a Postgres: `docs/runbooks/migracion-persistencia.md`.

## Aislamiento por organización en dos capas

Decisión en [ADR-034](adr/ADR-034-rls-por-tenant.md); migración
`db/alembic/versions/v128_rls_tenant_policies.py`.

1. **Capa primaria — aplicación.** `api/tenancy.py` resuelve la organización
   activa de cada petición y los repositorios de `db/` filtran por
   `organization_id`. Es el control que se prueba en
   `tests/test_organization_sql_isolation.py` y sigue siendo obligatorio.
2. **Respaldo — RLS por tenant.** Al resolver la organización,
   `api/tenancy.py` la deja en `shared/tenant_context.py` (un `ContextVar`
   que `anyio` copia al hilo del pool). `db/connection.py` emite `SET LOCAL
   app.organization_id = '<id>'` como primera sentencia de cada transacción
   con ámbito, y las políticas `tenant_scope_*` (permisiva) y `tenant_guard_*`
   (restrictiva) de cada tabla corporativa hacen invisibles las filas de
   otras organizaciones y rechazan insertarlas o moverlas allí. Un `WHERE`
   olvidado devuelve cero filas ajenas; un `INSERT` mal dirigido falla con
   `new row violates row-level security policy`.

Sin ámbito (scheduler, scripts, migraciones, backups) las políticas son paso
franco: la variable no está, o está a `''`, y se ve todo. Las filas legadas
con `organization_id NULL` siguen visibles desde cualquier ámbito. Una
operación que deba cruzar organizaciones dentro de una petición acotada lo
declara con `tenant_scope(None)` (hoy: `services/organizations.py::claim_legacy_scope`).

Límites que conviene tener presentes:

- Los superusuarios y los roles `BYPASSRLS` no están sujetos a RLS. El rol de
  la suite es superusuario, así que `tests/test_rls_tenant_scope_integration.py`
  ejerce las políticas con un rol sonda que emula a `tenderflow_app`.
- Solo las rutas que pasan por `api/tenancy.py` fijan ámbito; la vertical de
  pursuits resuelve la organización en `services/pursuits.py` y aún no lleva
  respaldo.
- Una tabla nueva con `organization_id` debe añadir `FORCE ROW LEVEL SECURITY`
  y las dos políticas en su migración, o declararse excluida con motivo en el
  test estructural; el test falla si no se decide.

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
  fallidos y sesiones server-side revocables con caducidad **deslizante**
  (`db/sessions.py`): cada petición validada vuelve a poner el plazo de
  inactividad en `now + SESSION_IDLE_HOURS` (24 h), sin superar nunca el techo
  absoluto `created_at + SESSION_ABSOLUTE_DAYS` (30 días), pasado el cual la
  sesión se rechaza aunque esté fresca. «Recordar este equipo» en el login
  alarga la ventana de inactividad a `SESSION_REMEMBER_DAYS` con el mismo
  techo. La renovación no toca `created_at` ni `mfa_verified_at`: las acciones
  sensibles (`require_recent_session`) siguen exigiendo login y segundo factor
  recientes con independencia de lo viva que esté la sesión.
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

## Auditoría

`audit_log` es una cadena de hashes firmada con HMAC (`db/audit.py`): cada
fila enlaza con la anterior y una cabecera firmada ancla el último hash y el
número de filas, así que se detectan tanto la alteración de una fila como el
borrado por la cola. Se verifica con `scripts/verify_audit_chain.py` o con
`GET /api/v1/security/audit/verify` (administración).

Desde 2026-09 los tipos de evento son un **catálogo cerrado** en
`shared/audit_events.py`. `db.audit.log_event` lo consulta de forma blanda: un
tipo fuera del catálogo se registra igual y deja `audit_event_type_unknown`
en el log — es un bug del llamante, no un motivo para perder el rastro.

| Familia | Eventos | Dónde se escriben |
|---|---|---|
| `org.*` | `created`, `deleted`, `settings_updated`, `nifs_updated`, `capabilities_updated`, `member_added`, `member_role_changed`, `member_removed`, `ownership_transferred`, `left`, `invitation_sent`, `invitation_resent`, `invitation_revoked`, `invitation_accepted` | `api/routes/pursuits.py`, `organization_settings.py`, `organizations_capacidad.py` |
| `auth.*` | `login_success`, `login_failed`, `logout`, `logout_all`, `password_reset_requested`, `password_reset_completed`, `totp_enabled`, `totp_disabled`, `session_revoked` | `api/routes/auth.py`, `api/routes/me.py` |
| `api_key.*` | `created`, `rotated`, `revoked` | `api/routes/me.py`; `revoked` lo emite la revocación por Secret Scanning de GitHub (`api/routes/security.py`) |
| `export.*` | `downloaded`, `calendar_link_created` | `api/routes/exports.py` |
| `gdpr.*` | `export`, `delete` | `api/routes/me.py` |
| `user.*` | `admin_changed`, `deactivate`, `reactivate`, `anonymize` | `api/routes/admin_users.py` |
| acceso | `solicitud_acceso.estado`, `access_grant.granted`, `access_grant.revoked` | `api/routes/admin_solicitudes.py` |
| `webhook.*` | `created`, `updated`, `deleted`, `secret_rotated` | `api/routes/webhooks.py` |
| configuración | `feature_flag.set`, `tecnologias_keyword.{added,removed,seeded}`, `empresa.review_resolved` | rutas de administración |
| operación | `dlq.requeued` | `api/routes/admin_dlq.py` |
| producto | `feedback.submitted`, `pursuit.weights_proposal_applied`, `go_no_go.weights_updated` | `api/routes/feedback.py`, `services/pursuits.py`, `services/go_no_go_puntuacion.py` |

Reglas del rastro (ADR-030 §D): el actor se guarda como `users.id` —columna
`user_id` desde v129 y `user_key = str(id)`—, nunca el correo. Los eventos de
organización llevan `resource="org:<id>"` y en `detail` solo ids (`user_id`,
`invitation_id`, recuentos); `auth.login_failed` contra una cuenta inexistente
no guarda la dirección tecleada. Los nombres persistidos antes del catálogo
(`auth.session_revoked`, `api_key.*`, `gdpr.export`, `gdpr.delete`) se
conservan: renombrarlos partiría el histórico y la etiqueta `event_type` de
`audit_events_total`.

### Export por organización

`GET /api/v1/organizations/{id}/audit` devuelve el rastro del tenant a su
owner o admin (un `member`/`viewer` recibe 403, igual que quien no es
miembro). Para API keys exige el scope `audit:read`, que `pursuits:read` **no**
implica. Parámetros: `desde`/`hasta` (fechas ISO en UTC, ambos días incluidos),
`limit` (hasta `MAX_PAGE_LIMIT`), `cursor` (el `next_cursor` de la página
anterior) y `formato=json|csv`. JSON responde
`CursorPaginatedResponse[AuditEntryOut]` (`id`, `ts`, `event_type`,
`actor_user_id`, `outcome`, `resource`, `detail`); CSV responde la misma
página con las celdas neutralizadas (`shared/export_safety.py`) y el cursor
siguiente en la cabecera `X-Next-Cursor`. Solo salen las filas con
`resource="org:<id>"`: los eventos de usuario (`auth.*`, `api_key.*`,
`gdpr.*`) son de la persona y viajan en su export GDPR (`GET /me/data`).

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

**Medición.** `python scripts/check_security_alerts.py`. Los avisos son estado
de GitHub y no del repositorio, así que el script los **consulta** con `gh` en
vez de derivarlos; lo que aporta el árbol es lo que convierte una lista en un
triaje: si el manifiesto del aviso sigue existiendo, y qué versión fija el
manifiesto que sí está vivo. Sin `gh` autenticado dice **NO MEDIDO** y sale con
0 — no «cumplido», que es la confusión que hace que la siguiente vulnerabilidad
de verdad se pierda entre los fantasmas.

### Triaje del 2026-09-08

Los tres avisos abiertos (dos altos, uno moderado) son **los tres fantasmas**:

| # | Sev. | Paquete | Manifiesto | Veredicto |
|---|---|---|---|---|
| 107 | alta | `cryptography` | `uv.lock` | El manifiesto no está en el árbol. `requirements.txt` fija `cryptography==50.0.0` y el aviso se parchea en `49.0.0`: lo desplegado no es vulnerable. |
| 106 | moderada | `cryptography` | `uv.lock` | Igual que el anterior. |
| 105 | alta | `transformers` | `uv.lock` | Ningún manifiesto vivo lo declara. Solo llega como transitiva de `sentence-transformers`, que es el extra opcional `[ml]` y no entra en el conjunto fijado. |

Ninguno tiene parche que aplicar, así que **el plazo de siete días no cuenta**:
lo que queda es descartarlos con motivo en la propia pestaña, que es acción del
mantenedor —esta sesión no cierra avisos de seguridad por su cuenta— y que la
sección «Avisos fantasma» de arriba ya prescribe.
