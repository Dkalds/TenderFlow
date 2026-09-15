---
tags: [plan, arquitectura, producto, estado]
---

# Plan de salida al mercado — ejecución de la revisión del 2026-09-13

**Origen.** Revisión de arquitectura y producto del 2026-09-13 («TenderFlow al
mercado»): cinco bloqueos para vender, seis decisiones previas y un roadmap en
tres horizontes. El mantenedor pidió el 2026-09-14 implementar **todo menos el
bloqueo I (capa comercial: planes, facturación, alta autoservicio, coste
unitario)**, que queda fuera de este plan de forma explícita.

**Convención.** Como en los planes anteriores: «hecho» es código en el árbol
con pruebas verdes; «parcial» entrega valor sin cumplir todos sus criterios;
«acción humana» es algo que un agente no puede ejecutar (paneles de Render,
Supabase, GitHub, etiquetado). Las cifras llevan fecha; lo que no se pudo
verificar desde el repositorio se dice.

---

## 1. Decisiones (D40–D45)

| Id | Decisión | Resuelta |
|---|---|---|
| D40 | **Posicionamiento:** radar tecnológico para integradores TI, dicho en voz alta; la taxonomía se ensancha *dentro* de TI (categorías además de fabricantes), no fuera. | 2026-09-14 — ejecutada por S-TAX |
| D41 | **Modelo de venta y alta autoservicio.** | **Fuera de alcance** por decisión del mantenedor (bloqueo I). No se toma aquí. |
| D42 | **Cobertura autonómica:** antes de abrir conectores para Madrid, Andalucía y Valencia, medir cuánto de su contratación TI llega ya por agregación a PLACSP. D16 se revisa con ese número. | 2026-09-14 — `make medir-solape` (S-COB). Ejecutarlo contra producción es acción humana. |
| D43 | **Plano de cron:** el worker de Render puede ejecutar el registry de jobs (`SCHEDULER_PLANE=worker`); Actions vuelve a ser CI cuando el humano haga el cutover. Revisa ADR-012. | 2026-09-14 — ADR-033 (S-CRON) |
| D44 | **Idiomas:** castellano en la UI; catalán, euskera y gallego en el dato (diccionario y filtro), porque los textos de PSCP, Euskadi y Galicia llegan en esas lenguas. | 2026-09-14 — S-TAX |
| D45 | **Aislamiento por tenant en dos capas:** la aplicación sigue siendo el control primario; RLS con `FORCE` sobre el dato corporativo es el respaldo. | 2026-09-14 — ADR-034 (S-RLS) |

---

## 2. Streams y estado

| Stream | Bloqueo | Qué entrega | Estado |
|---|---|---|---|
| S-RLS | V | `shared/tenant_context.py`, `SET LOCAL app.organization_id` en `db/connection.py`, políticas por tenant con `FORCE` (v128), tests de aislamiento, ADR-034 | **hecho** |
| S-UID | V | `user_id` en las tablas que aún dependían de `user_key`, backfill por email, lectura y escritura dual (v129), test de cambio de correo | _en curso al escribir esto; ver §5_ |
| S-SES | V | Sesiones deslizantes con techo absoluto, `remember` en el login, cookie y CSRF alineados | **hecho** |
| S-WHK | Plataforma | Firma v2 con timestamp y ventana de replay, rotación de secreto, doc de verificación | **hecho** |
| S-NIF | II/V | `nif_valido` / `clasificar_nif` (DNI, NIE, CIF); rechazo en NIF de organización; resolución de entidades no casa por NIF malformado; NIF vigilados inválidos se descartan | **hecho** |
| S-ML | III | Las cuatro columnas ML sobreviven a la re-ingesta; el merge nocturno acota candidatos | **hecho** |
| S-TAX | III | Taxonomía por categorías (ERP, CRM, cloud/infra, ciberseguridad, datos/IA, desarrollo, GIS, sanidad digital, administración electrónica) con vocabulario es/ca/eu/gl | _en curso_ |
| S-MAIL | Plataforma | `observability/mailer.py` con backends SMTP / Resend / Postmark / consola, `List-Unsubscribe`, runbook de correo | _en curso_ |
| S-CRON | IV | `SCHEDULER_PLANE=worker`, ADR-033, runbook de cutover | **hecho** (código); el cutover es acción humana |
| S-AUD | V | Catálogo de eventos de auditoría, cobertura de mutaciones de organización/auth/exports, export por organización | _en curso_ |
| S-COB | II | `dominios_documentos` en el inventario de fuentes, `make medir-solape`, `db/repositories/cobertura.py` | **hecho** |
| S-ORG | II | Paso canónico `organos_resolve` (resolución incremental), cobertura y cola en `/analytics/quality` | **hecho** |
| S-OPS | IV | Runbook de DR para Postgres, subencargados, resumen de seguridad, receptor de guardia documentado | **hecho** (docs); el receptor real es acción humana |

Ola 2 (tras la integración de lo anterior): `follows` (T1, v130), informes
programados (T6), superficie pública de la API (`x-public`), borrado lógico en
hijas de la oportunidad (v131), componente «Seguir» único y PDF desde la UI,
router de licitaciones por familias, vertical de pursuits bajo `api/tenancy`.

---

## 3. Acciones humanas que este plan deja listas pero no ejecuta

Todas están en el roadmap H0 de la revisión. Ninguna es código.

- [ ] Aplicar v98 → v131 en producción con `plan` antes de `apply`, por tandas, verificando `/health/ready → schema: ok` ([runbooks/disaster-recovery.md §5](../runbooks/disaster-recovery.md)).
- [ ] Vincular el Blueprint de Render, `autoDeploy: false`, un solo disparador.
- [ ] Receptor de guardia en `ALERTMANAGER_WEBHOOK_URL` ([runbooks/observability-alerts.md §8](../runbooks/observability-alerts.md)).
- [ ] Ejecutar `scripts/setup_pg_roles.sql`; runtime con `tenderflow_app`. **Hasta entonces el respaldo RLS de v128 está inerte** si el rol actual tiene `BYPASSRLS`.
- [ ] Ensayo completo de recuperación con tiempo medido (tabla §8 del runbook de DR).
- [ ] Rellenar `docs/COSTES.md` con las facturas y fijar el umbral.
- [ ] Dominio propio e identidad legal (`NEXT_PUBLIC_LEGAL_*`); regiones en [legal/subencargados.md](../legal/subencargados.md).
- [ ] Etiquetar 300 ejemplos del golden set (`scripts/sample_golden_candidates.py`).
- [ ] Decidir la activación de `baja_model` v2 y `retencion_model` v1 con el gate de `services/ml/promotion.py`.
- [ ] Ejecutar `make medir-solape` contra producción y anotar el número en el ítem de D16.
- [ ] Cutover del cron al worker ([runbooks/cutover-cron-al-worker.md](../runbooks/cutover-cron-al-worker.md)).
- [ ] Backfill del maestro de órganos (`scripts/backfill_organos.py --apply`); a partir de ahí lo incremental lo hace la pipeline.

---

## 4. Lo que este plan no hace, y por qué

- **Capa comercial** (planes, cuotas, Stripe, alta autoservicio, panel de uso): excluida por el mantenedor.
- **Conectores de Madrid, Andalucía y Valencia:** dependen de la medición de D42 contra producción.
- **Golden set de fichas y de clasificador:** requieren etiquetado humano; fabricarlos mediría el texto de quien los fabrica.
- **SAML/SCIM, P(ganar), broker de mensajería, microservicios, inglés en la UI:** siguen fuera (§8 del plan v2 y §«Lo que no haría» de la revisión).
- **Aligerar la imagen de la API** (sacar scikit-learn del proceso): exige partir los requirements y retirar el `/explain` síncrono por RFC; queda propuesto, no hecho.

---

## 5. Estado de ejecución

Se actualiza al cerrar cada stream. Cuenta lo que hay en el árbol, no lo que
se pretendía.

| Fecha | Qué |
|---|---|
| 2026-09-14 | S-RLS, S-SES, S-WHK, S-NIF, S-ML, S-COB, S-ORG y S-OPS en el árbol con pruebas verdes; S-UID, S-TAX, S-MAIL, S-CRON y S-AUD en curso. |
