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
| S-UID | V | `user_id` en las tablas que aún dependían de `user_key`, backfill por email, lectura y escritura dual (v129), test de cambio de correo | **hecho** |
| S-SES | V | Sesiones deslizantes con techo absoluto, `remember` en el login, cookie y CSRF alineados | **hecho** |
| S-WHK | Plataforma | Firma v2 con timestamp y ventana de replay, rotación de secreto, doc de verificación | **hecho** |
| S-NIF | II/V | `nif_valido` / `clasificar_nif` (DNI, NIE, CIF); rechazo en NIF de organización; resolución de entidades no casa por NIF malformado; NIF vigilados inválidos se descartan | **hecho** |
| S-ML | III | Las cuatro columnas ML sobreviven a la re-ingesta; el merge nocturno acota candidatos | **hecho** |
| S-TAX | III | Taxonomía por categorías (ERP, CRM, cloud/infra, ciberseguridad, datos/IA, desarrollo, GIS, sanidad digital, administración electrónica) con vocabulario es/ca/eu/gl | **hecho** |
| S-MAIL | Plataforma | `observability/mailer.py` con backends SMTP / Resend / Postmark / consola, `List-Unsubscribe`, runbook de correo | **hecho** |
| S-CRON | IV | `SCHEDULER_PLANE=worker`, ADR-033, runbook de cutover | **hecho** (código); el cutover es acción humana |
| S-AUD | V | Catálogo de eventos de auditoría, cobertura de mutaciones de organización/auth/exports, export por organización | **hecho** |
| S-COB | II | `dominios_documentos` en el inventario de fuentes, `make medir-solape`, `db/repositories/cobertura.py` | **hecho** |
| S-ORG | II | Paso canónico `organos_resolve` (resolución incremental), cobertura y cola en `/analytics/quality` | **hecho** |
| S-OPS | IV | Runbook de DR para Postgres, subencargados, resumen de seguridad, receptor de guardia documentado | **hecho** (docs); el receptor real es acción humana |

### Ola 2

| Stream | Qué entrega | Estado |
|---|---|---|
| S-FOLLOW | `follows` (v130) con backfill y escritura doble desde las tres tablas de origen, endpoints `/follows`, `scripts/check_follows_paridad.py` | **hecho** (fase aditiva de ADR-031 §B; la lectura no se mueve hasta que la paridad dé cero contra producción) |
| S-SOFT | `deleted_at` en comentarios, tareas y adjuntos (v131), con el guardarraíl que exige el filtro en toda lectura | **hecho** |
| S-PUB | `api/superficie_publica.py`, `x-public` en el spec completo y `api/openapi-public.json` filtrado | **hecho** |
| S-UI | «Descargar PDF» en la oportunidad; control `SeguirBoton` único sobre `/follows`, estrenado en el panel de órgano | **parcial** — ver §4 |
| S-INF | Informe semanal por organización (T6, v132): programación día/hora/destinatarios, correo HTML con PDF adjunto, opt-out por usuario, paso canónico advisory | **hecho** |
| S-ROUTER | Router de licitaciones por familias y un solo identificador | **no hecho** — ver §4 |
| S-PURSUIT | Vertical de pursuits bajo `api/tenancy` | **no hecho** — ver §4 |

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

### Lo de Ola 2 que se queda fuera, y qué falta exactamente

- **Migrar los tres controles «Seguir» existentes a `/follows`** (S-UI, parcial).
  El componente único existe y se usa donde antes no había nada —seguir un
  órgano—, pero la estrella del expediente, el botón de empresa y el descarte
  del radar siguen leyendo de su tabla. Y tienen que seguir: ADR-031 §B pone
  como condición que `scripts/check_follows_paridad.py` dé **cero** contra
  producción, y eso es una ejecución humana (§3). Mover la lectura antes
  convertiría un fallo del backfill en favoritos que desaparecen, que es
  exactamente el riesgo que la fase aditiva existe para no correr.
- **Router de licitaciones por familias y un solo identificador.** No empezado.
  Es una refactorización grande de `api/routes/licitaciones.py` sin cambio de
  comportamiento: alto riesgo de regresión y ningún valor visible para el
  cliente mientras el resto de la Ola 2 esté sin cerrar. Se prioriza después.
- **Vertical de pursuits bajo `api/tenancy`.** No empezado. El respaldo que
  motivaba parte de esto —la RLS por tenant— ya está puesto (v128), así que lo
  que queda es la uniformidad del código, no una brecha de aislamiento.

---

## 4-bis. Lo que queda en rojo y no se ha podido cerrar

Tres tests fallan **sólo** en la suite completa en paralelo (`pytest -n 4`), y
no siempre los mismos:

| Test | Síntoma |
|---|---|
| `test_webhooks_rotate_secret.py` (dos o tres, rotando) | 401 en una petición cuya sustitución de `require_any_auth` el test acaba de instalar |
| `test_ops_events.py::test_healthcheck_ops_events_tabla_ausente` | `ops_events_missing` no llega a `True` tras borrar la tabla |

Qué está establecido: los tres pasan en solitario, pasan con `-p no:randomly`,
y pasan en una tirada en paralelo acotada a sus vecinos más probables
(los ficheros que también vacían `app.dependency_overrides`). En tres tiradas
completas fallaron tests **distintos** del mismo fichero cada vez, que es la
firma de contaminación entre tests, no de una regresión.

Qué se ha hecho: `_sin_ssrf` deja de vaciar `app.dependency_overrides` entero
—vaciaba un diccionario global compartido con otros veintiún ficheros— y la
aserción de `_crear` ahora dice qué mirar cuando falla. Con eso el fichero deja
de ser una **fuente** de contaminación; que siga siendo **víctima** de alguna
otra no se ha logrado reproducir, y por tanto no se ha arreglado. Queda como
ítem abierto, no como algo cerrado en silencio.

## 5. Estado de ejecución

Se actualiza al cerrar cada stream. Cuenta lo que hay en el árbol, no lo que
se pretendía.

| Fecha | Qué |
|---|---|
| 2026-09-14 | S-RLS, S-SES, S-WHK, S-NIF, S-ML, S-COB, S-ORG y S-OPS en el árbol con pruebas verdes; S-UID, S-TAX, S-MAIL, S-CRON y S-AUD en curso. |
| 2026-09-15 | **T6 (informes programados)** cerrado: v132, `services/informes.py`, adjuntos en el transporte y la extracción de `_build_pdf` que el plan de Ola 2 marcaba como su prerrequisito. Queda documentado en [informes-programados.md](../informes-programados.md). |
| 2026-09-15 | **Ola 1 cerrada**: S-UID, S-TAX, S-MAIL, S-CRON y S-AUD terminados. De Ola 2 entran S-FOLLOW (v130), S-SOFT (v131), S-PUB y la mitad de S-UI. Quedan fuera S-ROUTER y S-PURSUIT (§4); S-INF entra el mismo día, en la fila de arriba. Tres hallazgos de los guardarraíles nuevos, corregidos aquí: `.net` llevaba en el diccionario desde su primera versión **sin poder clasificar nada** (`\\b` antes de un punto no casa tras un espacio); las menciones de un comentario seguían sirviendo su texto después de borrarlo; y los CIF de los fixtures no tenían letra de control válida, así que la resolución de entidades los anulaba. |
