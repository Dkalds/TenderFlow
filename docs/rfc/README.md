# RFC Format — licitaciones-sap

Todos los RFCs siguen esta estructura.

> **Sobre los roles de agente (corregido el 2026-09-03).** Este README decía que
> «el agente **architect** es responsable de producirlos», y la plantilla de
> abajo sigue admitiendo `author: agent:architect`. Ese esquema multi-rol
> (orchestrator, architect, coder, test_engineer, reviewer, security_triage) se
> **retiró el 2026-07-30** junto con la denylist por rol que lo sostenía: hoy no
> hay roles, hay agentes que siguen `AGENTS.md`. El campo `author` se conserva
> por compatibilidad con los RFCs ya escritos —y porque `docs/adr/discussions/`
> hay que leerlo con esa clave—, pero en un RFC nuevo se pone quién lo escribió
> de verdad. Quién produce un RFC y cuándo hace falta está en `AGENTS.md` §5, no
> aquí.

## Índice

<!-- BEGIN indice-rfc (generado por scripts/gen_rfc_index.py — no editar a mano) -->

**70 RFC**, de los cuales **16** siguen abiertos. `approved` 1 · `implemented` 48 · `obsolete` 4 · `partially-implemented` 15 · `superseded` 2.

**Criterio de `implemented`: que el código exista en el árbol, no que el PR se haya mergeado.** Un RFC cuyo código está pero cuyo PR quedó abierto está implementado; uno cuyo PR se mergeó sin dejar código, no.

La columna «Evidencia» sale del campo `evidence:` del frontmatter del propio RFC. Un RFC `implemented` sin evidencia declarada no falla el check, pero obliga a quien lo lea a buscarla: declarala.

Esta tabla se genera con `python scripts/gen_rfc_index.py`; CI la verifica con `--check`, y un RFC sin `status` —o con uno fuera del vocabulario— lo hace fallar.

| Estado | Significado |
|---|---|
| `approved` | Acordado; el código todavía no existe. |
| `draft` | Borrador, sin acordar. |
| `implemented` | El código existe en el árbol. |
| `obsolete` | Ya no aplica (la arquitectura que describe no existe). |
| `partially-implemented` | Parte del código existe; el RFC dice qué falta. |
| `rejected` | Descartado. |
| `review` | En revisión. |
| `superseded` | Sustituido por otro RFC o graduado a ADR. |

| RFC | Estado | Fecha | Evidencia |
|---|---|---|---|
| [Plan integral ejecutable para 7 mejoras transversales (typing, CI tests, markers, migraciones, observabilidad, DX Windows, graphify)](2026-05-28-rfc-plan-integral-7-mejoras.md) | `approved` | 2026-05-28 | — |
| [Documentar la fachada db.database](001-documentar-facade-db-database.md) | `implemented` | 2026-05-24 | — |
| [Add PEP 561 py.typed marker to shared/ package](040-py-typed-marker-shared.md) | `implemented` | 2026-05-24 | — |
| [Fortalecer validación de secretos y contraseñas en arranque](042-rotar-secretos-fortalecer-passwords.md) | `implemented` | 2026-05-24 | — |
| [Cifrar secretos TOTP almacenados en texto plano](043-encrypt-totp-secrets.md) | `implemented` | 2026-05-24 | — |
| [GDPR get_user_id_from_key_id debe retornar None en lugar de fallback al primer usuario](044-gdpr-fallback-fix.md) | `implemented` | 2026-05-24 | — |
| [Fix silent DB initialization error in dev/staging](046-fix-silent-db-init-error.md) | `implemented` | 2026-05-24 | — |
| [Fix race condition en close_pool() — lock durante drain del pool](047-close-pool-race-condition.md) | `implemented` | 2026-05-24 | — |
| [Fix get_stored_hash silent exception swallowing enabling timing attacks](048-get-stored-hash-exception-handling.md) | `implemented` | 2026-05-24 | — |
| [Eliminar secretos de webhook en texto plano usando derivación HMAC](049-encrypt-webhook-secrets.md) | `implemented` | 2026-05-24 | — |
| [Fix IDOR en export jobs — validar ownership por key_hash](050-idor-export-jobs.md) | `implemented` | 2026-05-24 | — |
| [Uso consistente de _trusted_client_ip para prevenir IP spoofing](051-trusted-client-ip-consistency.md) | `implemented` | 2026-05-24 | — |
| [Alinear reset_timeout inicial del CircuitBreaker con BREAKER_BASE_TIMEOUT](052-circuit-breaker-dead-code.md) | `implemented` | 2026-05-24 | — |
| [Chunked upsert_licitaciones_with_history para liberar write lock](053-upsert-chunking.md) | `implemented` | 2026-05-24 | — |
| [Fix incorrect condition in tracing.py that allows spans without OpenTelemetry configured](056-fix-tracing-condition.md) | `implemented` | 2026-05-24 | — |
| [Añadir rate limiting al endpoint /api/v1/ask (LLM)](058-rate-limit-ask-endpoint.md) | `implemented` | 2026-05-24 | — |
| [No cachear valores None en config/secrets.py](059-secrets-none-cache-retry.md) | `implemented` | 2026-05-24 | — |
| [Dockerfile.api CMD: exec form para propagación correcta de señales](061-dockerfile-api-exec-form.md) | `implemented` | 2026-05-24 | — |
| [OAuth nonce store: fail-closed con fallback in-memory](062-oauth-nonce-fail-closed.md) | `implemented` | 2026-05-24 | — |
| [Migrar MaxBodyMiddleware de BaseHTTPMiddleware a raw ASGI](063-maxbody-raw-asgi-middleware.md) | `implemented` | 2026-05-24 | — |
| [Fix broken Make targets — heredoc indentation and stale type-ignore](085-fix-broken-verifications.md) | `implemented` | 2026-05-26 | — |
| [Linaje analítico canónico — manifest Parquet y orden de materialización](086-linaje-analitico-parquet-manifest.md) | `implemented` | 2026-06-09 | — |
| [Enrutar violaciones de integridad del upsert a la DLQ (recuperabilidad)](2026-06-16-rfc-dlq-violaciones-integridad-upsert.md) | `implemented` | 2026-06-16 | — |
| [Normalización canónica de fechas ISO-8601 en el boundary de ingesta CODICE](2026-06-16-rfc-normalizacion-canonica-fechas-ingesta.md) | `implemented` | 2026-06-16 | — |
| [Observabilidad de pérdida de filas en el upsert de adjudicaciones (INSERT OR IGNORE)](2026-06-16-rfc-observabilidad-perdida-filas-upsert.md) | `implemented` | 2026-06-16 | — |
| [Soft-delete + anonimización de usuarios (preservar audit trail, GDPR Art.17)](2026-06-16-rfc-soft-delete-anonimizacion-usuarios.md) | `implemented` | 2026-06-16 | — |
| [TTL en el cache de secrets — rotación de vault sin reiniciar el proceso](2026-06-16-rfc-ttl-cache-secrets.md) | `implemented` | 2026-06-16 | — |
| [UX · Administración — usuarios reales (no MOCK_USERS) y gestión funcional](2026-06-16-rfc-ux-administracion.md) | `implemented` | 2026-06-16 | — |
| [UX/KPIs · Clusters — guía de calidad para elegir K e interpretabilidad de clusters](2026-06-16-rfc-ux-clusters.md) | `implemented` | 2026-06-16 | — |
| [UX/KPIs · Ecosistema Partners — grafo de co-licitación real (UTE/co-adjudicación), no co-ocurrencia por CCAA](2026-06-16-rfc-ux-ecosistema-partners.md) | `implemented` | 2026-06-16 | — |
| [UX · Feature Flags — lista dirigida por backend (no hardcode), persistencia y auditoría](2026-06-16-rfc-ux-feature-flags.md) | `implemented` | 2026-06-16 | — |
| [UX/IA · Licitadores vs Competidores — eliminar redundancia (mismo endpoint) o diferenciar propósito](2026-06-16-rfc-ux-licitadores.md) | `implemented` | 2026-06-16 | — |
| [UX/KPIs · Mi Watchlist — persistir reglas en servidor y alertas reales (hoy localStorage)](2026-06-16-rfc-ux-mi-watchlist.md) | `implemented` | 2026-06-16 | — |
| [UX/KPIs · Órganos — totales reales (no sobre el top-50) y drill-down al listado](2026-06-16-rfc-ux-organos.md) | `implemented` | 2026-06-16 | — |
| [UX/KPIs · Pipeline/Alertas — alertas reales suscribibles y clarificar IA vs renovaciones/calendario](2026-06-16-rfc-ux-pipeline-alertas.md) | `implemented` | 2026-06-16 | — |
| [UX/KPIs · Proyectos/Módulos — KPIs a nivel licitación (sin doble conteo multi-módulo) y drill-down](2026-06-16-rfc-ux-proyectos-modulos.md) | `implemented` | 2026-06-16 | — |
| [UX/KPIs · Red Órgano-Empresa — grafo de adjudicaciones reales (no aristas inventadas por CCAA)](2026-06-16-rfc-ux-red-organo-empresa.md) | `implemented` | 2026-06-16 | — |
| [UX/KPIs · Tecnologías — cobertura del clasificador (sin_clasificar) accionable y bridge al listado](2026-06-16-rfc-ux-tecnologias.md) | `implemented` | 2026-06-16 | — |
| [UX/KPIs · UTEs — relaciones de co-licitación (quién se asocia con quién) y drill-down](2026-06-16-rfc-ux-utes.md) | `implemented` | 2026-06-16 | — |
| [Observabilidad de tokens y coste en el cliente LLM](2026-06-17-rfc-observabilidad-tokens-coste-llm.md) | `implemented` | 2026-06-17 | — |
| [UX · Active Learning — más contexto por item, etiquetado multi-tecnología y desglose de probabilidades por clase](2026-06-28-rfc-ux-active-learning-multi-tech.md) | `implemented` | 2026-06-28 | — |
| [UX · Grafos Red Órgano-Empresa y Ecosistema Partners — rehacer la capa de visualización (ForceGraph) y cerrar el drill-down](2026-06-28-rfc-ux-grafos-red-partners.md) | `implemented` | 2026-06-28 | — |
| [LLM como dependencia gestionada — presupuesto, circuit-breaker, fallback degradado y eval de RAG](2026-06-30-rfc-llm-dependencia-gestionada.md) | `implemented` | 2026-06-30 | — |
| [Retrofit del pipeline PLACSP sobre el contrato Connector (cerrar la bifurcación de ingesta)](2026-06-30-rfc-retrofit-pipeline-placsp-connector.md) | `implemented` | 2026-06-30 | `scraper/connectors/placsp.py`, `scheduler/pipeline_runs.py` |
| [Validación de la precisión del dedupe cross-fuente y linaje de datos como contrato testeable](2026-06-30-rfc-validacion-dedupe-linaje-datos.md) | `implemented` | 2026-06-30 | — |
| [Scoring de oportunidades genérico (sin tecnología hardcodeada)](2026-07-04-rfc-scoring-generico.md) | `implemented` | 2026-07-04 | — |
| [Enlaces firmados sin sesión para el calendario ICS y la baja de correos](2026-09-02-rfc-enlaces-firmados-sin-sesion.md) | `implemented` | 2026-09-02 | `shared/signing.py`, `GET /exports/calendario/enlace` |
| [Conceder acceso OAuth desde el producto con auditoría](242-acceso-oauth-dinamico.md) | `implemented` | 2026-09-01 | `db/access_grants.py`, `db/alembic/versions/v95_access_grants.py`, `api/routes/admin_solicitudes.py` |
| [Recuperación segura de contraseña para cuentas locales](243-recuperacion-contrasena-local.md) | `implemented` | 2026-09-01 | `db/password_reset.py`, `services/password_reset.py`, `db/alembic/versions/v96_password_reset_tokens.py` |
| [Implementar CSRF tokens para sesiones del dashboard](057-csrf-tokens-dashboard.md) | `obsolete` | 2026-05-24 | — |
| [Añadir dashboard como scrape target de Prometheus](060-prometheus-dashboard-scrape.md) | `obsolete` | 2026-05-24 | — |
| [RFC de handoff humano: bloqueos por denylist](2026-05-28-implementacion-bloqueos-denylist.md) | `obsolete` | 2026-05-28 | — |
| [UX · Relaciones → Estructura de mercado: del hairball a vistas orientadas a preguntas (concentración, ego-network, drill-down de arista)](2026-07-21-rfc-relaciones-estructura-mercado.md) | `obsolete` | 2026-07-21 | Cita `services/organ_concentration.py` y `red_organo_empresa.py`, borrados |
| [Fase 5 — Conectores autonómicos (PSCP Catalunya primero) y resoluciones TACRC](2026-06-11-rfc-conectores-autonomicos-tacrc.md) | `partially-implemented` | 2026-06-11 | — |
| [Fase 6 — Modelos predictivos: baja ganadora y probabilidad de adjudicación](2026-06-11-rfc-modelos-predictivos.md) | `partially-implemented` | 2026-06-11 | — |
| [UX/KPIs · Active Learning — cerrar el bucle (impacto en el modelo) y etiquetado multi-clase](2026-06-16-rfc-ux-active-learning.md) | `partially-implemented` | 2026-06-16 | — |
| [UX/KPIs · Calendario — datos diarios reales y reorientar a vencimientos accionables](2026-06-16-rfc-ux-calendario.md) | `partially-implemented` | 2026-06-16 | — |
| [UX/KPIs · Calidad de Datos — integridad completa (drops de escritura, fechas, tendencia, DLQ accionable)](2026-06-16-rfc-ux-calidad-datos.md) | `partially-implemented` | 2026-06-16 | — |
| [UX/KPIs · Competidores — trayectoria temporal, señales proactivas y coherencia de filtros](2026-06-16-rfc-ux-competidores.md) | `partially-implemented` | 2026-06-16 | — |
| [UX/KPIs · Detalle — score inline alineado con la paginación (no merge con top-500 disjunto)](2026-06-16-rfc-ux-detalle.md) | `partially-implemented` | 2026-06-16 | — |
| [UX/KPIs · Empresas — perfil con posicionamiento competitivo, trend temporal y drill-down](2026-06-16-rfc-ux-empresas.md) | `partially-implemented` | 2026-06-16 | — |
| [UX/KPIs · Geografía — agregación de provincias en backend (no sample de 500) y drill-down](2026-06-16-rfc-ux-geografia.md) | `partially-implemented` | 2026-06-16 | — |
| [UX/KPIs · Investigador — fidelidad de filtros en búsqueda y citas/feedback del RAG](2026-06-16-rfc-ux-investigador.md) | `partially-implemented` | 2026-06-16 | — |
| [UX/KPIs · Observabilidad — URL de Grafana por config (no localhost), salud en vivo y rol vs calidad-datos](2026-06-16-rfc-ux-observabilidad.md) | `partially-implemented` | 2026-06-16 | — |
| [UX/KPIs · Renovaciones — priorizar por riesgo de cambio (modelo de retención), no solo importe](2026-06-16-rfc-ux-renovaciones.md) | `partially-implemented` | 2026-06-16 | — |
| [UX/KPIs · Resumen — deltas consistentes, KPIs accionables y arreglo de CCAA cubiertas](2026-06-16-rfc-ux-resumen.md) | `partially-implemented` | 2026-06-16 | — |
| [UX/KPIs · Tendencias CPV — forecast por CPV (no global) y drill-down](2026-06-16-rfc-ux-tendencias-cpv.md) | `partially-implemented` | 2026-06-16 | — |
| [UX/KPIs · Tendencias — heatmap real Mes×Estado, banda de forecast theme-safe, drill-down](2026-06-16-rfc-ux-tendencias.md) | `partially-implemented` | 2026-06-16 | — |
| [Meta-RFC · Integridad analítica del frontend — el frontend no fabrica datos; backend = única fuente de verdad analítica](2026-06-16-rfc-meta-integridad-analitica-frontend.md) | `superseded` | 2026-06-16 | Graduado a `docs/adr/ADR-014-integridad-analitica-frontend.md` |
| [Plan de migración de persistencia pre-cocido con disparador binario (SQLite/Turso → Postgres)](2026-06-30-rfc-plan-migracion-persistencia-pre-cocido.md) | `superseded` | 2026-06-30 | — |

<!-- END indice-rfc -->

---

## Nombre de archivo

`docs/rfc/NNN-slug-descriptivo.md`

Donde `NNN` es el número de issue de GitHub con padding a 3 dígitos (ej: `042-documentar-facade-db.md`).

---

## Plantilla

```markdown
---
rfc: NNN
title: <título descriptivo>
issue: <URL del issue de GitHub>
author: <agent:architect | human:nombre>
date: YYYY-MM-DD
status: draft | review | approved | rejected | superseded | implemented | partially-implemented | obsolete
supersedes: <RFC anterior si aplica>
---

## Contexto

<¿Por qué se necesita este cambio? ¿Qué problema resuelve? Referencias a ADRs relevantes.>

## Decisión

<La decisión técnica propuesta, descrita con precisión. Qué se hace, qué NO se hace.>

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| ... | ... | ... | ... |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Ninguno / Afecta módulo X | ... |
| §3.2 Upsert idempotente | Ninguno / Nueva operación Y | ... |
| §3.3 Migraciones append-only | Ninguno / Nueva migración Z | ... |
| §3.4 Auto-marking tests | Ninguno | — |
| §3.5 Pydantic v2 DTOs | Ninguno / Campo W cambia | ... |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. <Paso 1 — archivo(s) afectados>
2. <Paso 2>
3. ...

**Archivos de partida**: `<lista de archivos relevantes>`
**Riesgo estimado**: bajo | medio | alto
**Tiempo estimado**: <N horas/días>

## Acceptance criteria

- [ ] <Criterio verificable 1>
- [ ] <Criterio verificable 2>
- [ ] `make lint && make typecheck && make test-unit` pasan en verde
- [ ] diff-cover ≥ 80% en líneas nuevas

## Notas de review

<Comentarios del reviewer y security_triage durante la etapa agent:rfc-review.
Formato: `YYYY-MM-DDTHH:MMZ agent:reviewer — <comentario>`>
```

---

## Estados del ciclo de vida

| Status | Label de issue | Significado |
|---|---|---|
| `draft` | `agent:rfc-draft` | Generado por architect, pendiente de review |
| `review` | `agent:rfc-review` | Bajo revisión de reviewer + test_engineer |
| `approved` | `agent:rfc-approved` | Listo para que el coder implemente |
| `rejected` | — | Descartado con justificación |
| `superseded` | — | Reemplazado por otro RFC (ver campo `supersedes`) |
| `implemented` | — | Implementado y verificado en código (todos los acceptance criteria cumplidos) |
| `partially-implemented` | — | Criterio/bug central implementado y verificado; criterios secundarios diferidos (ver notas de review) |
| `obsolete` | — | Ya no aplica (problema desaparecido o resuelto por otra vía) |
