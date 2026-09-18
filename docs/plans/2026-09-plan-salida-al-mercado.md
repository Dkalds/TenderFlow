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
| S-ROUTER | Paquete `api/routes/licitaciones/` por familias; `{id_externo:path}` en toda ruta de expediente; el catch-all del detalle sale de `api/app.py` | **hecho** |
| S-PURSUIT | El respaldo RLS cubre también la vertical de pursuits: el ámbito lo arma `resolve_organization`, no el llamante | **hecho** |

---

## 3. Acciones humanas que este plan deja listas pero no ejecuta

Todas están en el roadmap H0 de la revisión. Ninguna es código.

- [ ] Aplicar v98 → **v132** en producción con `plan` antes de `apply`, por tandas, verificando `/health/ready → schema: ok` ([runbooks/disaster-recovery.md §5](../runbooks/disaster-recovery.md)).
- [ ] Vincular el Blueprint de Render, `autoDeploy: false`, un solo disparador.
- [ ] Receptor de guardia en `ALERTMANAGER_WEBHOOK_URL` ([runbooks/observability-alerts.md §8](../runbooks/observability-alerts.md)).
- [ ] Ejecutar `scripts/setup_pg_roles.sql`; runtime con `tenderflow_app`. **Hasta entonces el respaldo RLS de v128 está inerte** si el rol actual tiene `BYPASSRLS`.
- [ ] Ensayo completo de recuperación con tiempo medido (tabla §8 del runbook de DR).
- [ ] Rellenar `docs/COSTES.md` con las facturas y fijar el umbral.
- [ ] Dominio propio e identidad legal (`NEXT_PUBLIC_LEGAL_*`); regiones en [legal/subencargados.md](../legal/subencargados.md).
- [ ] Etiquetar 300 ejemplos del golden set (`scripts/sample_golden_candidates.py`).
- [ ] Decidir la activación de `baja_model` v2 y `retencion_model` v1 con el gate de `services/ml/promotion.py`.
- [ ] Ejecutar `make medir-solape` contra producción y anotar el número en el ítem de D16.
- [ ] Mirar la serie `follows_paridad_faltan` en `ops_events` y, si lleva 30 días en cero, ejecutar el cutover de «Seguir» ([runbooks/cutover-follows.md](../runbooks/cutover-follows.md)). Ya no hay que ejecutar nada para medirlo: el paso `follows_paridad` lo hace a diario.
- [ ] Cutover del cron al worker ([runbooks/cutover-cron-al-worker.md](../runbooks/cutover-cron-al-worker.md)).
- [ ] Backfill del maestro de órganos (`scripts/backfill_organos.py --apply`); a partir de ahí lo incremental lo hace la pipeline.

---

## 4. Lo que este plan no hace, y por qué

- **Capa comercial** (planes, cuotas, Stripe, alta autoservicio, panel de uso): excluida por el mantenedor.
- **Conectores de Madrid, Andalucía y Valencia:** dependen de la medición de D42 contra producción.
- **Golden set de fichas y de clasificador:** requieren etiquetado humano; fabricarlos mediría el texto de quien los fabrica.
- **SAML/SCIM, P(ganar), broker de mensajería, microservicios, inglés en la UI:** siguen fuera (§8 del plan v2 y §«Lo que no haría» de la revisión).
- **Aligerar la imagen de la API** (sacar scikit-learn del proceso): exige partir los requirements y retirar el `/explain` síncrono por RFC. *Actualización 2026-09-18:* requirements partidos y la imagen de la API ya no instala scikit-learn (rama `worktree-agent-aa37c7b64b746caaa`); `/explain` responde 503 y su retirada o precálculo es la RFC [2026-09-18-rfc-explain-fuera-del-proceso-api](../rfc/2026-09-18-rfc-explain-fuera-del-proceso-api.md), pendiente de decisión.

### Lo de Ola 2 que se queda fuera, y qué falta exactamente

- **Migrar los tres controles «Seguir» existentes a `/follows`** (S-UI, parcial).
  El componente único existe y se usa donde antes no había nada —seguir un
  órgano—, pero la estrella del expediente, el botón de empresa y el descarte
  del radar siguen leyendo de su tabla. Y tienen que seguir: ADR-031 §B pone
  como condición que la paridad dé **cero** contra producción. Mover la lectura
  antes convertiría un fallo del backfill en favoritos que desaparecen, que es
  exactamente el riesgo que la fase aditiva existe para no correr.

  Lo que sí se ha cerrado (2026-09-15) es el otro lado del bloqueo: la medición
  era «acción humana — ejecutar el script contra producción», y un número que
  hay que ir a buscar no es un número que exista. Ahora la mide el paso
  `follows_paridad` de la pipeline, a diario, en `ops_events`. La acción humana
  que queda es leer la serie y decidir, con el procedimiento escrito en
  [runbooks/cutover-follows.md](../runbooks/cutover-follows.md).

---

## 4-bis. Los tests que fallaban en paralelo: causa y arreglo

**Cerrado el 2026-09-15.** Durante cinco tiradas completas, `pytest -n 4` dejó
dos tests de `tests/test_webhooks_rotate_secret.py` en rojo — nunca los mismos
dos— con un 401 en una petición cuya sustitución de `require_any_auth` el test
acababa de instalar. Pasaban en solitario, con `-p no:randomly`, y con `-n 4`
sobre los 23 ficheros que tocan `app.dependency_overrides`.

**La causa.** `tests/test_unit_dockerfile_api.py` comprueba que importar
`api.app` no arrastra `torch` ni `lxml` —el corte de la imagen de la API—, y
para medirlo borraba `api.app` de `sys.modules` y lo reimportaba. No reponía el
original. `api/app.py` crea el objeto `app` al importarse y una veintena de
ficheros de test hacen `from api.app import app` **en la colección**, así que a
partir de ese punto convivían dos objetos `app`: el que aquellos capturaron y
el que resuelve el fixture `client`. Sus `dependency_overrides` son
diccionarios distintos. El test instalaba su sustitución en un `app` que ya no
respondía, y la petición salía sin autenticar.

El orden aleatorio decidía si esos dos tests corrían antes de los de webhooks
en el mismo worker. De ahí que fallaran dos por tirada y nunca los mismos.

**Por qué costó.** El síntoma —un 401— señala a la autenticación, y el fallo
estaba en `sys.modules`. Las tres hipótesis razonables (un vecino que vacía
`dependency_overrides`, un middleware, dos objetos `require_any_auth`
distintos) eran falsas y se descartaron una a una. Lo resolvió imprimir
`id(app)` desde el test que fallaba, en una tirada completa instrumentada: el
`app` del módulo y el del `TestClient` tenían identidades distintas.

**El arreglo.** `_api_app_descargada` repone el módulo original al salir —y el
atributo del paquete, que es la mitad que se olvida: `from api.app import app`
resuelve por `sys.modules` y `import api.app as m` por el atributo, así que
reponer sólo uno deja el fallo vivo y más raro—. Y un fixture autouse en
`tests/conftest.py` compara las dos identidades antes y después de cada test:
si alguien vuelve a dejar un `api.app` recargado, falla **ese** test con el
motivo escrito, en vez de un 401 tres ficheros más allá. No fuerza el import de
la API si el test no la tocó.

Tirada completa tras el arreglo: **6.880 pasan, 0 fallan** (`-n 4`).

## 5. Estado de ejecución

Se actualiza al cerrar cada stream. Cuenta lo que hay en el árbol, no lo que
se pretendía.

| Fecha | Qué |
|---|---|
| 2026-09-14 | S-RLS, S-SES, S-WHK, S-NIF, S-ML, S-COB, S-ORG y S-OPS en el árbol con pruebas verdes; S-UID, S-TAX, S-MAIL, S-CRON y S-AUD en curso. |
| 2026-09-15 | **T6 (informes programados)** cerrado: v132, `services/informes.py`, adjuntos en el transporte y la extracción de `_build_pdf` que el plan de Ola 2 marcaba como su prerrequisito. Queda documentado en [informes-programados.md](../informes-programados.md). |
| 2026-09-15 | **S-PURSUIT** cerrado, y la premisa de este plan sobre él era falsa. Aquí decía que «el respaldo que motivaba parte de esto —la RLS por tenant— ya está puesto (v128), así que lo que queda es la uniformidad del código, no una brecha de aislamiento». No lo estaba: el ámbito de `shared.tenant_context` lo fijaba únicamente `api/tenancy.py`, y las 47 rutas de pursuits resuelven desde `services/pursuits.py`, así que corrían **sin ámbito**. Como el predicado de v128 deja pasar todo con el GUC vacío, el respaldo no fallaba: estaba apagado, en silencio, justo en las tablas de oportunidades, comentarios, tareas y adjuntos. Ningún test lo vio porque falla abierto. Se cerró con `alcance_resuelto`, un context manager que resuelve y acota el bloque, en las ~28 entradas de la vertical. El primer intento —fijar el ámbito dentro de `resolve_organization`— parecía mejor y estaba mal: un `set` sin final deja el ámbito clavado en el hilo de cualquier llamante síncrono, y la suite lo dijo con `test_tenant_context` entero en rojo. Test de regresión bajo el rol sin `BYPASSRLS`. |
| 2026-09-15 | **S-ROUTER** cerrado, y no salió gratis: se dio por «refactor sin cambio de comportamiento» y resultó tener dos bugs vivos. `GET /licitaciones/{id}/similares` y la página de un documento daban **404** con los `id_externo` de PLACSP que llevan barra —la mayoría— porque eran las dos únicas sub-rutas con el conversor por defecto; y el detalle sólo funcionaba por un `add_api_route(include_in_schema=False)` al final de `api/app.py`, que dejaba el **esquema** publicando la variante rota. Ahora `{id_externo:path}` en las 25 rutas (las tres que decían `licitacion_id` incluidas), el detalle en su propio router incluido el último, y `tests/test_licitaciones_identificador.py` fija el orden. El módulo de 1.612 líneas es un paquete de seis familias. De paso, el ratchet de `user_key` tenía un hueco: sus tests comprobaban que *sabría* detectar un fichero nuevo pero no lo corrían contra el árbol, así que T6 lo había roto y sólo habría caído en CI. |
| 2026-09-15 | **Ola 1 cerrada**: S-UID, S-TAX, S-MAIL, S-CRON y S-AUD terminados. De Ola 2 entran S-FOLLOW (v130), S-SOFT (v131), S-PUB y la mitad de S-UI. Quedan fuera S-ROUTER y S-PURSUIT (§4); S-INF entra el mismo día, en la fila de arriba. Tres hallazgos de los guardarraíles nuevos, corregidos aquí: `.net` llevaba en el diccionario desde su primera versión **sin poder clasificar nada** (`\\b` antes de un punto no casa tras un espacio); las menciones de un comentario seguían sirviendo su texto después de borrarlo; y los CIF de los fixtures no tenían letra de control válida, así que la resolución de entidades los anulaba. |
