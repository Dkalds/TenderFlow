# Subencargados y ubicación del tratamiento

**Estado: borrador para revisión del propietario (2026-09-14).** Complementa el
[registro de tratamientos](registro-tratamientos.md) §3 y §4 y el
[anexo de encargo](anexo-encargo-tratamiento.md). Las casillas marcadas
**propietario** solo puede rellenarlas quien tiene acceso a los paneles de cada
proveedor; no se inventan.

Un cliente B2B pregunta tres cosas antes de firmar: quién más toca sus datos,
dónde y con qué base de transferencia. Este documento las contesta desde lo que
el repositorio puede afirmar y deja explícito lo que no.

---

## 1. Lista de subencargados

| Proveedor | Qué hace | Qué dato ve | Región declarada | Dónde consta | Mecanismo de transferencia |
|---|---|---|---|---|---|
| **Supabase** (Postgres) | Base de datos de producción | Todas las categorías del registro | **propietario: confirmar en el panel** (`Project → Settings → General`) | `DATABASE_URL` (fuera del repo) | **propietario** (DPA de Supabase; SCC si la región no es UE) |
| **Render** | API, worker, Prometheus, Alertmanager, Grafana | Peticiones, logs de aplicación (con secretos redactados), métricas | `frankfurt` (`render.yaml`, cinco servicios) | `render.yaml` | DPA de Render; tratamiento en la UE |
| **Vercel** | Frontend Next.js, logs de acceso, RUM (`@vercel/analytics`, `@vercel/speed-insights`) | IP, user-agent, rutas; eventos de producto de baja cardinalidad (`web/src/lib/analytics.ts`) | Edge global; funciones en la región del proyecto (**propietario: confirmar**) | proyecto de Vercel (fuera del repo) | DPA de Vercel |
| **GitHub** (Actions) | Plano de cron de producción (ADR-012): ingesta, ML, backups, healthcheck | Conecta a la base con credenciales de producción desde runners **en EE. UU.** | `ubuntu-latest` (EE. UU.) | `.github/workflows/*.yml` | DPA de GitHub + SCC. **Se elimina como subencargado de datos al mover el cron al worker ([ADR-033](../adr/ADR-033-plano-de-cron-en-el-worker.md))**; hasta entonces es un tratamiento fuera del EEE que hay que declarar |
| **AWS S3 / Cloudflare R2** | Copia remota cifrada de los backups (`backup.yml`) | Dump completo, cifrado con AES-256 antes de salir (GPG) | **propietario: región del bucket** | `BACKUP_S3_BUCKET` (secret) | DPA del proveedor; el dato viaja cifrado y la clave no sale de GitHub Secrets ni del gestor del propietario |
| **Google** (SMTP Gmail) | Envío de correo transaccional y alertas | Direcciones de correo de usuarios, contenido de invitaciones, digestos y recuperación de contraseña | Global | `ALERT_SMTP_*` | DPA de Google Workspace. Sustituible por un ESP con dominio propio (ver [correo-transaccional.md](../runbooks/correo-transaccional.md)) |
| **Google / Microsoft** (OIDC) | Identidad federada | Email y nombre del perfil al iniciar sesión | Global | `api/routes/auth.py` | Responsables independientes de su lado (no subencargados) |
| **NVIDIA NIM / OpenAI / Anthropic** (LLM, opcional) | Asistente `/ask`, ficha del pliego, etiquetado tecnológico | **Texto de licitaciones y pliegos, que es dato público**; el prompt no incluye identidad del usuario ni dato de la organización (ver `llm/prompts.py`, `services/rag/`). Presupuesto y proveedor por configuración | EE. UU. (por defecto) | `NVIDIA_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Sin dato personal por diseño; si un cliente exige que ni el texto público salga del EEE, se desactiva con `PLIEGO_FACTS_ENABLED=false` y sin clave de LLM |
| **Sentry** (opt-in) | Errores de aplicación | Trazas con PII eliminada (`observability/sentry.py`) | Según la organización de Sentry (**propietario**) | `SENTRY_DSN` | DPA de Sentry; desactivado si no hay DSN |

## 2. Lo que no hay

- No hay proveedor de pagos ni de facturación (no existe la capa comercial).
- No hay proveedor de soporte con acceso a la base (no hay impersonación).
- No hay CDN ni almacén de objetos con dato personal: los binarios del almacén
  ([ADR-029](../adr/ADR-029-almacen-de-objetos.md)) son pliegos públicos y
  adjuntos de oportunidad (dato corporativo, bucket privado, enlaces firmados).

## 3. Casillas que solo el propietario puede cerrar

- [ ] Región del proyecto de Supabase y, si no es UE, el mecanismo (SCC + TIA).
- [ ] Región de funciones del proyecto de Vercel.
- [ ] Región del bucket de backups.
- [ ] Organización y región de Sentry, si está activo.
- [ ] Fecha y versión del DPA firmado con cada proveedor (enlace al documento).
- [ ] Aviso a clientes ante alta de un subencargado nuevo: plazo (30 días es el
      habitual) y canal, que se escriben en el
      [anexo de encargo](anexo-encargo-tratamiento.md).

Cuando estas casillas estén cerradas, este documento se enlaza desde
`/seguridad` en la superficie pública.
