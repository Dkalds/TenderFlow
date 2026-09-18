# Resumen de seguridad para cuestionarios de clientes

**Fecha: 2026-09-14.** Este documento responde, con lo que el repositorio puede
afirmar, a las preguntas habituales de un cuestionario de seguridad B2B. Cada
respuesta enlaza al control real. Lo que **no** existe se dice en §12, porque
un cuestionario respondido con optimismo se descubre en la auditoría de
cumplimiento del cliente, no antes.

Las casillas marcadas **propietario** requieren datos que no viven en el
repositorio (regiones contratadas, contratos firmados) y las rellena quien
tiene acceso a los paneles.

---

## 1. Alojamiento y ubicación del dato

| Componente | Proveedor | Región | Detalle |
|---|---|---|---|
| API, worker, observabilidad | Render | Frankfurt (UE) | `render.yaml`, cinco servicios |
| Base de datos | Supabase (Postgres) | **propietario** | `DATABASE_URL` con `sslmode=verify-full` obligatorio en producción |
| Frontend | Vercel | edge global; funciones **propietario** | Next.js, sin acceso a la base |
| Backups | S3 / R2 | **propietario** | cifrados antes de salir (§7) |
| Cron de producción | GitHub Actions | EE. UU. | en migración al worker de Render ([ADR-033](adr/ADR-033-plano-de-cron-en-el-worker.md)) |

Lista completa de subencargados y mecanismos de transferencia:
[legal/subencargados.md](legal/subencargados.md).

## 2. Cifrado

- **En tránsito:** HTTPS en toda superficie pública (HSTS, `api/middleware.py`);
  TLS verificado contra la base (`config/settings.py::_validate_prod_database_ssl`).
- **En reposo:** el que provee cada plataforma (Supabase, Render, Vercel). No hay
  claves por cliente ni BYOK (§12).
- **Cifrado de aplicación, adicional:** secretos TOTP con Fernet
  (`shared/crypto.py`, `TOTP_ENCRYPTION_KEY`), secretos de webhook derivados de
  una clave maestra (`db/webhooks.py`, RFC 049), backups con GPG AES-256
  (`backup.yml`), contraseñas con Argon2id (`shared/auth_core.py`).

## 3. Identidad y acceso

- **Autenticación:** contraseña con Argon2id y política de complejidad
  (`shared/password_policy.py`); OIDC con Google y Microsoft Entra ID (PKCE,
  `nonce`, `state` firmado con HMAC, anti-replay en Redis); TOTP como segundo
  factor, obligatorio en `ENV=prod` para acciones sensibles.
- **Sesiones:** cookie `HttpOnly`, `Secure`, `SameSite=Lax`; renovación por
  actividad con techo absoluto (`SESSION_IDLE_HOURS`, `SESSION_ABSOLUTE_DAYS`,
  `db/sessions.py`); revocación individual y global desde `/ajustes`.
- **Autorización:** roles por organización (`owner`, `admin`, `member`,
  `viewer`), scopes por operación centralizados en `api/scopes.py` y
  verificados en CI contra `docs/api-design.md`.
- **Acceso al producto:** por invitación o solicitud aprobada; sin alta libre
  (`ALLOW_SELF_REGISTRATION=false`).

## 4. Aislamiento entre clientes

Dos capas ([ADR-034](adr/ADR-034-rls-por-tenant.md)):

1. **Aplicación:** cada petición resuelve la organización en un único punto
   (`api/tenancy.py`) y los repositorios filtran por `organization_id`; un test
   estructural impide que una ruta lo esquive.
2. **Base de datos:** políticas RLS por tenant con `FORCE ROW LEVEL SECURITY`
   sobre las tablas de dato corporativo (v128): dentro de una petición acotada,
   las filas de otra organización no existen para la consulta, y un `INSERT`
   para otra organización falla. Un test ejecuta los repositorios como
   organización ajena y exige cero filas.

## 5. Auditoría

- `audit_log` encadenado con SHA-256/HMAC por entrada (`db/audit.py`), verificable
  con `scripts/verify_audit_chain.py` y `GET /api/v1/security/audit/verify`.
- Catálogo cerrado de eventos (`shared/audit_events.py`): organización,
  miembros, invitaciones, capacidad y NIF, autenticación, sesiones, claves API,
  exportaciones, GDPR, webhooks.
- Export por organización para owner/admin (`GET /api/v1/organizations/{id}/audit`,
  JSON y CSV). El log guarda identificadores, nunca copia correos (ADR-030 §D).

## 6. Desarrollo seguro

- Tipado estricto, `ruff`, `mypy`, `bandit`, `codespell`, `gitleaks` y
  `detect-secrets` en pre-commit y en CI; Semgrep (OWASP Top 10) y Trivy sobre
  la imagen semanalmente; `pip-audit` y `npm audit` en cada push.
- Fuzzing de contrato de la API sin 5xx (`scripts/fuzz_api_contract.py`),
  mutación semanal, cobertura mínima por módulo.
- Dependencias fijadas y actualizadas por Dependabot/Renovate.
- Cabeceras: CSP con informe de violaciones (`/api/v1/security/csp-report`),
  HSTS, `X-Frame-Options`, `Permissions-Policy`, `Referrer-Policy`.
- SSRF: toda URL saliente pasa por `shared/ssrf.py` con allowlist por dominio
  y bloqueo de rangos privados y DNS rebinding.
- Límites: tamaño de cuerpo, rate limit global y por clave API con tiers, cuotas
  de gasto LLM por día, usuario y organización.

## 7. Continuidad y recuperación

- Backup diario cifrado a almacén remoto (`backup.yml`, 03:00 UTC), retención
  documentada en [SECURITY.md](SECURITY.md#retención-de-datos).
- Drill semanal de restauración en base efímera (`restore-drill.yml`).
- Runbook de recuperación ante desastre para Postgres
  ([runbooks/disaster-recovery.md](runbooks/disaster-recovery.md)); RTO 2 h y
  RPO 24 h **declarados**, ensayo de extremo a extremo pendiente (tabla §8 del
  runbook).

## 8. Monitorización e incidentes

- Prometheus + Alertmanager + Grafana desplegados; reglas en
  `observability/alert_rules.yml`; `Watchdog` como dead-man's-switch.
- Receptor de guardia: pendiente de configurar
  ([runbooks/observability-alerts.md §8](runbooks/observability-alerts.md)).
- Playbooks por escenario en [runbooks/incident-playbooks.md](runbooks/incident-playbooks.md).
- Sentry opcional con PII eliminada; logs estructurados con secretos redactados.

## 9. Datos personales y RGPD

- Registro de actividades del art. 30 y anexo de encargo del art. 28 en
  [legal/](legal/) (borradores para revisión jurídica).
- Export completo del usuario (`GET /api/v1/me/data`) y borrado con
  anonimización del histórico que debe conservarse (`DELETE /api/v1/me`).
- Separación entre dato personal y corporativo (ADR-030 §D): quien se va no se
  lleva el trabajo del equipo; la organización que se borra se lleva lo suyo.
- Retención por tabla generada desde código y verificada en CI.

## 10. Datos de contratación pública

Los expedientes, pliegos y adjudicaciones son datos públicos reutilizados al
amparo de la Ley 37/2007. La superficie pública indexable no publica nada de
`adjudicaciones` ni derivados del pipeline propio; la proyección es una
allowlist verificada en CI (`make check-public-surface`). El asistente y la
ficha del pliego envían al proveedor LLM solo texto público, nunca identidad
del usuario ni datos de la organización.

## 11. Vulnerabilidades

Política y canal de reporte en [SECURITY.md](SECURITY.md#reporte-de-vulnerabilidades).
Triaje registrado con fecha; los avisos de Dependabot se cierran con motivo.

## 12. Lo que no hay (y no se afirma)

- Certificaciones SOC 2 o ISO 27001; programa de evidencias.
- Pentest externo con informe.
- Claves de cifrado por cliente (BYOK/CMK).
- SAML y SCIM (solo OIDC; se construyen contra contrato, ADR-030 §B).
- Página de estado pública y SLA contractual de disponibilidad (SLO suspendido
  hasta confirmar el plan del servicio, `docs/sli-slo.md`).
- Región de Supabase, de las funciones de Vercel y del bucket de backups
  documentadas: **propietario**.
- Ensayo completo de recuperación con tiempo medido.
- Segunda persona con acceso operativo a todos los proveedores.
