---
tags: [plan, arquitectura, producto, multi-agente]
---

# Plan complementario 2026-09 — lo que v2 dejó fuera

Complementa [2026-09-plan-arquitectura-v2.md](2026-09-plan-arquitectura-v2.md)
(en adelante **v2**) con los puntos que aquel plan no cubre: la semántica del
dato y los maestros que faltan, el ciclo de vida de cuentas y organizaciones,
la plataforma y su coste, la calidad de la ingesta, el conocimiento (RAG, ficha
y diccionario), la colaboración de captura, la accesibilidad, el contrato de
la API y la documentación que el código desmiente en una segunda tanda.
Redactado el 2026-09-05 sobre el mismo árbol que v2 (rama
`claude/app-architecture-review-d3vcog`, base `master` = `17169ce`); cada
hecho lleva su referencia y lo que no se pudo comprobar se dice.

No repite nada de v2 ni del plan de septiembre. Cuando un ítem depende de un
stream de v2, lo cita por su identificador (`v2 S4`, `v2 T1`). Comparte con
ellos el contrato de ejecución: un stream por rama y por agente, este documento
como única fuente de alcance y criterios, y propiedad exclusiva de ficheros.

**Estado: PROPUESTO el 2026-09-05.** Nada de este documento está implementado.

## 0. Alcance y método

**Qué cubre.** Nueve streams complementarios (C1–C9) sin ola propia de
operación: la Ola 0 de v2 sigue siendo el prerrequisito de todo lo que hay
aquí, y ningún stream de este documento arranca antes de v2 O0.1, O0.2 y O0.5.

**Qué queda fuera.** El backup y el restore drill, por decisión del mantenedor
del 2026-09-05: no aparecen en ningún ítem, métrica ni gate. Tampoco lo que v2
ya planifica (identidad y equipo, capacidad de la organización, lotes,
outbox, cola, etiquetas del ML, documentos, seguimiento unificado, núcleo
tipado, pre-radar, informes) ni lo que el plan de septiembre dio por hecho.

**Convenciones.** Las de v2: esfuerzo **S** / **M** / **L**, gates **[§6]**
de AGENTS.md salvo lo que D31 pre-autoriza, y criterios de aceptación
verificables con un comando, un test o una consulta. Las cifras llevan fecha y
se vuelven a medir, no se corrigen a mano. Las decisiones continúan la
numeración de v2 (D21 en adelante).

**Corrección a v2, registrada.** El ítem O0.7 de v2 afirmaba en su apartado
(c) que la tabla de características del README daba TED por pendiente. Es
falso: la línea 11 del README ya lista TED entre las fuentes activas cada
cuatro horas; la advertencia desfasada está en la cabecera de
`web/src/app/(publico)/_content/landing.ts`, que atribuye al README un
desfase que no tiene. v2 se corrige en el mismo cambio que crea este
documento, y el hecho 32 de abajo recoge lo que sí está desfasado en el
README. Un plan que no registra sus errores los repite.

## 1. Hechos verificados (2026-09-05)

### Datos y semántica

1. **El importe mezcla bases.** `scraper/codice_parser.py` toma
   `cbc:TaxExclusiveAmount` y, si falta, cae a `cbc:TotalAmount`, que lleva
   IVA (`codice_parser.py:491-499`, `651-653`; lotes en `448-450`). La fila no
   guarda cuál de los dos fue, y el valor estimado del contrato
   (`EstimatedOverallContractAmount`) no se extrae (sin coincidencias).
   Bajas, escenarios de precio y scoring comparan importes de base distinta
   sin saberlo.
2. **No hay maestro de órganos.** `organo_contratacion` es texto libre; la
   analítica agrupa y cuenta por ese texto
   (`db/repositories/aggregates.py:245`, `services/analytics/organos.py:113`)
   y el parser no extrae el código DIR3 (sin coincidencias de `DIR3` ni
   `schemeName`). El maestro de empresas sí existe desde `v35`, con alias y
   cola de revisión.
3. **Ni predecesor ni similares.** `services/embeddings.py:92` sabe buscar
   textos similares y ninguna ruta de `api/` ni pantalla de `web/` lo expone
   (sin coincidencias de `similares`). El único uso del concepto de
   incumbente es el modelo de retención (`services/ml/retencion_labels.py`).
4. **Republicaciones sin decisión.** `detect_republicaciones` marca siempre
   `pending` (`services/dedupe.py:32-33`, `:288`); el plan de septiembre
   (S1.8) dejó en ADR-026 la decisión de ocultarlas o mostrarlas y ADR-026 no
   la contiene (sin coincidencias de `republicaci`).
5. **PSCP persiste sin señal.** El conector calcula keywords solo sobre el
   título y persiste el aviso aunque no encuentre ninguna
   (`scraper/connectors/pscp.py:350-370`). El backlog mide 683 k filas con
   0,46 % de positivos: es el corpus que ahoga al clasificador (v2 S6.1).
6. **Embeddings sin versión.** `EMBEDDING_VERSION` (`config/settings.py:439`)
   no lo lee ningún módulo; `documento_chunks` no guarda modelo ni versión
   (`v56` solo lo menciona en un comentario). Cambiar de modelo no tiene
   camino.

### Cuentas y seguridad

7. **Sesiones invisibles.** `db/sessions.py:269` implementa
   `list_active_sessions` y nadie lo llama: el usuario solo tiene
   `POST /auth/logout-all`.
8. **La organización no tiene ciclo de vida.** No hay traspaso de owner ni
   borrado de organización (sin coincidencias de `transfer` ni
   `delete_organization`); `_guard_owner_row` lo declara en su docstring
   (`services/organizations.py:83-92`).
9. **API keys sin autoservicio ni tiers.** La creación vive en
   `api/auth.py:259` y solo la usa un script; `/me/keys` lista y rota, no
   crea. `api_key_tiers` existe desde `v28` con columna `tier` en `api_keys`,
   y ninguna ruta ni middleware la lee (sin coincidencias de `tier` en
   `api/auth.py`, `api/middleware.py`, `api/scopes.py`,
   `services/rate_limiting.py`).
10. **Webhooks sin reintento.** `db/webhooks.py:216-229` cuenta fallos y
    desactiva al superar el umbral; no hay backoff ni re-entrega (sin
    coincidencias de `retry` ni `backoff`).
11. **Vulnerabilidades abiertas.** El push del 2026-09-05 reportó tres avisos
    en la rama por defecto (dos altos, uno moderado); el backlog P3 añade 37
    avisos fantasma por el `uv.lock` borrado.
12. **Errores de cliente sin destino.** `POST /security/client-error` termina
    en `log.warning` (`api/routes/security.py`); no hay tabla ni vista en
    `/ops` (sin coincidencias en `web/src/app/(dashboard)/ops`). Sentry es
    opt-in y solo backend; el frontend no tiene SDK.
13. **Sin preferencias de notificación.** Ninguna tabla ni servicio las
    modela; v2 S4.6 las necesita y no dice dónde viven.

### Plataforma y coste

14. **Sin alerta de latencia.** `observability/alert_rules.yml` define
    Watchdog, `ApiErrorRateHigh`, `LLMBudgetExceeded`, dos reglas de dedupe y
    cinco de Postgres; ninguna sobre `http_request_duration_seconds` (SLO 6)
    ni sobre RUM (SLO 3), como ya reconoce `docs/sli-slo.md`.
15. **Una imagen para todo.** 33 dependencias de runtime de API, pipeline y
    ML en la misma imagen (backlog P2); el OOM del 2026-08-02 es el síntoma.
16. **Un schema por test.** `tests/conftest.py:219` construye un schema
    Postgres por test; el backlog P2 lo señala como techo de velocidad de la
    suite.
17. **Sin staging ni hoja de costes.** Staging es un P3 del backlog por
    coste; no existe ningún documento de costes en `docs/` (sin
    coincidencias).
18. **`graphify-out/` pesa 17 MB** (`du -sh`, 2026-09-05; el backlog citaba 28).

### Conocimiento

19. **La ficha no tiene golden set** (backlog P2) y su selección de páginas
    coexiste con el retrieval pgvector: dos selectores para el mismo pliego.
20. **`/ask` no cita.** Los chunks entran al prompt con `documento_id` y
    `page_number` (`llm/prompts.py:238`), pero la respuesta es texto libre;
    solo el modo de extracción exige `evidence` (`llm/prompts.py:145`).
21. **El feedback del asistente no se persiste.** El voto de
    `web/src/components/chat-thread.tsx` es un evento de telemetría
    (`web/src/lib/analytics.ts`) y no llega a ninguna tabla (sin
    coincidencias en `api/routes/feedback.py` ni `db/repositories/feedback.py`).
22. **El diccionario de tecnologías es código.** `config/keywords.py`;
    `scraper/lineage.py::current_filter_version` versiona el filtro. Añadir
    una keyword es un deploy.

### Frontend

23. **Accesibilidad a medias.** Cuatro reglas axe desactivadas
    (`web/e2e/accessibility.spec.ts:67-72`: `color-contrast`,
    `nested-interactive`, `scrollable-region-focusable`, `target-size`) y
    cuatro `test.fixme` (dos en `critical-workflows.spec.ts`, dos en
    `responsive.spec.ts`). `nested-interactive` afecta a «Seguir» en el
    Radar (backlog P2).
24. **152 apariciones de `title=`** en `.tsx` (grep 2026-09-05; el backlog
    contaba 137 nativos con otro criterio).
25. **Sin presupuesto de bundle.** `@next/bundle-analyzer` no está (sin
    coincidencias en `web/package.json` ni `web/next.config.ts`) pese a
    pedirlo S5.6 del plan de septiembre.
26. **S5.8 del plan de septiembre sigue sin hacer** (piso de cobertura de
    `src/app/**` y axe sobre la superficie pública), según su §8.
27. **Primer uso y portada.** Onboarding parcial, captura oscura para el tema
    claro e identidad publicada por variables que solo el propietario puede
    rellenar (backlog P2 y UX_AUDIT).

### API y contrato

28. **Sin detector de cambios breaking.** `codegen-drift` (`ci.yml:566`)
    detecta desfase entre OpenAPI y `api.d.ts`, no incompatibilidades; no hay
    política de deprecación escrita y el listado por offset emite
    `Deprecation: true` sin `Sunset`.
29. **Contrato sin consumidor.** `tests/test_pursuits_api_contract.py` y
    `tests/test_contract_dto.py` fijan códigos de error y forma de DTO;
    ninguno valida los fixtures que usa el frontend contra el esquema del
    backend (Fase 8 del plan de producto).

### Documentación

30. **`docs/api-design.md`** cita `/exports/{job_id}`, `/webhooks/{id}/test` y
    `/models/{name}/rollback` (líneas 151-152), rutas que no existen; su tabla
    de scopes tiene ocho filas frente a las ~20 familias de `api/scopes.py`;
    sigue diciendo FTS5 (línea 141).
31. **`docs/c4-architecture.md`** dibuja un contenedor «Scheduler,
    APScheduler» cuando producción orquesta con GitHub Actions
    (`docs/runbook.md`); **`docs/AGENT_PLAYBOOK.md`** glosa FAISS como índice
    vigente cuando se retiró el 2026-07-04 (README).
32. **README** lista `db/migrations.py` (línea 93), que no existe, y describe
    `scraper/pipeline.py` como «orquestador principal» (línea 111) tras su
    retirada de los caminos vivos (S2 del plan de septiembre).
    `.pre-commit-config.yaml` (líneas 54 y 110) sigue incluyendo un directorio
    `dashboard/` que no existe.
33. **La retención no está publicada.** Los plazos viven en
    `scheduler/retention.py` como constantes y argumentos, y no hay tabla en
    `docs/SECURITY.md` ni en los runbooks (sin coincidencias).
34. **v2 exige ADR que no nombra.** El worker revisa ADR-012, el almacén de
    objetos revisa la decisión «texto por página, sin blob store» del plan de
    producto, el outbox y la cola añaden persistencia que ADR-022 debe
    conocer. ADR-026 es el último.

### Cifras de partida

| Magnitud | Valor | Medido |
|---|---|---|
| Reglas axe desactivadas / `test.fixme` | 4 / 4 | `web/e2e`, 2026-09-05 |
| Apariciones de `title=` en `.tsx` | 152 | grep, 2026-09-05 |
| Reglas de alerta de latencia | 0 | `observability/alert_rules.yml` |
| Avisos de seguridad en la rama por defecto | 3 (2 altos, 1 moderado) | salida del push, 2026-09-05 |
| Peso de `graphify-out/` | 17 MB | `du -sh`, 2026-09-05 |
| Familias de scope documentadas / existentes | 8 / ~20 | `docs/api-design.md`, `api/scopes.py` |
| Ficheros de docs que citan rutas inexistentes | 3 (README, api-design, pre-commit) | grep, 2026-09-05 |

## 2. Decisiones del mantenedor (D21–D31)

| Id | Decisión | Desbloquea |
|---|---|---|
| D21 | **Semántica del importe.** ¿Tres columnas aditivas (`importe_base_sin_iva`, `importe_con_iva`, `valor_estimado`) más `importe_tipo` para el histórico, o un solo `importe` con `importe_tipo`? Propuesta: tres columnas; `importe` se conserva como alias de la base sin IVA y `importe_tipo` etiqueta lo ya ingerido. | C1.1 |
| D22 | **Maestro de órganos.** ¿Clave DIR3 cuando exista y nombre normalizado como respaldo, con cola de revisión como en empresas? Propuesta: sí, mismo patrón que `empresas`. | C1.2 |
| D23 | **Republicaciones `pending`.** ¿Ocultas en Radar y superficie pública y visibles en Detalle con aviso, o visibles en todas partes? Propuesta: ocultas en Radar y público, visibles en Detalle con badge; se registra en ADR-026. | C4.2 |
| D24 | **PSCP.** ¿Acotar en el conector al universo tecnológico (no persistir sin señal) o seguir ingiriendo el censo y excluirlo en los agregados? Propuesta: acotar en el conector con contador de descartados. | C4.1 |
| D25 | **API keys.** ¿Claves de organización además de personales, y tiers aplicados en el rate limit? Propuesta: sí a ambas; tier por defecto `standard`. | C2.3 |
| D26 | **Errores de frontend.** ¿SDK externo (coste, PII) o tabla propia con vista en `/ops`? Propuesta: tabla propia, sin SDK. | C2.6 |
| D27 | **Staging.** ¿Entorno permanente, preview por PR con schema efímero, o ninguno? Propuesta: preview por PR solo para la API; sin staging permanente. | C3.5 |
| D28 | **Diccionario de tecnologías como dato.** ¿Tabla versionada editable desde `/ops` con `filter_version` derivado del contenido, o seguir en código? Propuesta: tabla con versión por hash y preview de impacto. | C5.6 |
| D29 | **Citas en `/ask`.** ¿Exigir citas estructuradas y marcar «sin fuentes en el pliego» cuando no las hay? Propuesta: sí. | C5.3 |
| D30 | **Plantilla de go/no-go.** ¿Cinco criterios fijos con pesos por organización, o criterios definidos por cada organización? Propuesta: cinco fijos con pesos. | C6.4 |
| D31 | **Gates §6 pre-autorizados para este plan.** Migraciones de C1, C2, C4.6, C5, C6 en los términos de cada ítem; edición de `ci.yml`, `security.yml` y `pliegos.yml` en los términos de C3, C7 y C8; `.env.example` para `RETENTION_*` y las variables de C2; dependencias `@next/bundle-analyzer`, `oasdiff` (o equivalente) y las de C1.2 si hacen falta. Todo lo demás pide OK puntual. | todos |

Mientras D21–D30 no estén cerradas, los ítems que las citan no se empiezan.
Un agente que necesite una decisión no tomada la deja escrita en el PR y se
detiene ahí.

---

## 3. Streams

| Stream | Rama | Migración | Depende de | Merge |
|---|---|---|---|---|
| C1 Datos maestros y semántica | `claude/c1-maestros` | v112 (importe), v113 (órganos), v114 (`organo_id`) | v2 O0.1 | tras v2 S1 |
| C2 Cuentas y seguridad | `claude/c2-cuentas` | v115 (keys de organización), v116 (`client_errors`), v117 (preferencias) | C2.4 y C2.7 de v2 S4/S5 | libre |
| C3 Plataforma y coste | `claude/c3-plataforma` | no | C3.5 de v2 O0.2 | libre |
| C4 Ingesta y calidad | `claude/c4-ingesta` | v118 (tablas de salud) | C4.1 antes de v2 S6.1 | libre |
| C5 Conocimiento | `claude/c5-conocimiento` | v119 (`asistente_feedback`), v120 (diccionario), v121 (versión de embeddings) | C5.6 coordina con v2 T3 | tras C4 |
| C6 Colaboración y captura | `claude/c6-captura` | v122 (tareas), v123 (plantilla go/no-go), v124 (notas) | v2 S3 y S4; C6.3 de v2 S8.1 | tras v2 S4 |
| C7 Frontend y accesibilidad | `claude/c7-frontend` | no | C7.5 de C2.1, C2.3 y C2.7 | libre |
| C8 API y contrato | `claude/c8-contrato` | no | C8.1 con v2 O0.6e | libre |
| C9 Documentación, ADR y proceso | `claude/c9-docs` | no | C9.1 antes de los streams de v2 que cita | primero y último |

**Propiedad exclusiva de ficheros:**

- `scraper/codice_parser.py`, `db/upsert.py` (campos de importe y órgano),
  `db/repositories/organos.py`, `services/organos.py`,
  `services/similares.py`, `services/competitive/bajas.py`,
  `db/repositories/pricing.py`: C1.
- `api/routes/me.py`, `api/routes/auth.py` (sesiones), `db/sessions.py`,
  `db/repositories/api_keys.py`, `api/auth.py`, `api/middleware.py` (tiers),
  `db/webhooks.py` (entregas), `services/organizations.py` (ciclo de vida),
  `api/routes/security.py`, `db/repositories/client_errors.py`,
  `db/repositories/notification_preferences.py`, `docs/SECURITY.md`: C2.
- `requirements*.in`, `docker/Dockerfile.api`, `observability/alert_rules.yml`,
  `tests/conftest.py`, `docs/COSTES.md`, `docs/sli-slo.md`: C3.
- `scraper/connectors/pscp.py`, `scraper/connectors/euskadi.py`,
  `scraper/connectors/galicia.py`, `services/dedupe.py`,
  `scripts/audit_domain_truth.py`, `scheduler/healthcheck.py`,
  `db/repositories/source_health.py`, `services/analytics/quality.py`: C4.
- `services/rag/**`, `llm/**`, `services/ml_eval.py`,
  `db/repositories/feedback.py`, `api/routes/feedback.py`,
  `config/keywords.py`, `db/repositories/tecnologias_keywords.py`,
  `scraper/lineage.py`, `services/embeddings.py`,
  `scheduler/jobs/documentos_embeddings.py`: C5.
- `db/repositories/pursuit_tasks.py`, `services/pursuit_tasks.py`,
  `services/pursuit_comments.py` (menciones), `services/go_no_go_template.py`,
  `services/exports.py`, `web/src/app/(dashboard)/oportunidades/**`,
  `web/src/app/(dashboard)/mi-pipeline/**`: C6.
- `web/**` salvo lo asignado a C6, más `web/e2e/**`: C7.
- `api/errors.py`, `api/routes/analytics.py` (deprecaciones),
  `scripts/check_openapi_contract.py`, `scripts/check_contract_fixtures.py`,
  `.github/workflows/ci.yml` (jobs de contrato): C8.
- `docs/**` salvo el backlog, `.pre-commit-config.yaml`, `README.md`,
  `scripts/check_agent_docs.py`, `scripts/check_backlog_freshness.py`,
  `scripts/gen_rfc_index.py`, `scripts/gen_retention_doc.py`: C9.
- `shared/dto.py` y `docs/IMPROVEMENT_BACKLOG.md`: cada stream, solo su
  sección y sus ítems.

### C1 — Datos maestros y semántica del dato

**Objetivo:** que un importe diga de qué base es, que un órgano sea una
entidad y no una cadena, y que un expediente conozca a su predecesor.

1. **Importe con semántica (D21).** El parser extrae `TaxExclusiveAmount`,
   `TotalAmount` y `EstimatedOverallContractAmount` por separado y el upsert
   los persiste en tres columnas más `importe_tipo`; `bajas`, `pricing` y
   `scoring` usan solo la base sin IVA y lo declaran. Esfuerzo M · **[§6]**
   migración, pre-autorizada.
   *Aceptación:* test del parser con un fixture que trae los tres importes;
   `scripts/audit_domain_truth.py` cuenta `importe_tipo IS NULL` en filas
   nuevas con umbral 0; `/competitive/bajas` y `/escenarios-precio` responden
   `base: sin_iva`; un test de paridad sobre un fixture mixto demuestra que
   ningún cálculo de baja mezcla tipos; el delta de `make audit-truth-check`
   antes y después queda anotado.
2. **Maestro de órganos (D22).** Tablas `organos` (`id`, `nombre_canonico`,
   `dir3`, `ccaa`, `tipo`, `url_perfil`), `organo_aliases` y cola de revisión
   con el patrón de `empresas`; el parser extrae DIR3 cuando CODICE lo trae;
   `licitaciones.organo_id` nullable con backfill por
   `services/dedupe.normalize_organo`; la analítica de órganos agrupa por
   `organo_id`. Esfuerzo L · **[§6]** dos migraciones, pre-autorizadas.
   *Aceptación:* al menos el 95 % de los expedientes de PLACSP de los últimos
   doce meses con `organo_id` (script de medición con fecha); dos grafías del
   mismo órgano en un fixture resuelven al mismo perfil; `/analytics/organos`
   solo cambia de cifra por fusiones, y el delta se anota; la página de
   órgano enlaza al perfil del contratante.
3. **Predecesor y similares.** `services/similares.py`: con el embedding de
   título y objeto, el CPV a cuatro dígitos y el órgano, propone `predecesor`
   (contrato adjudicado anterior del mismo órgano con solapamiento de objeto
   y fechas) y hasta diez `similares` de cualquier órgano;
   `GET /licitaciones/{id}/similares` tipado; el inspector muestra
   incumbente, importe y baja anteriores. Sin embeddings cae a FTS y declara
   `metodo`. Esfuerzo M.
   *Aceptación:* golden `tests/fixtures/golden_predecesor.jsonl` con treinta
   pares y precisión ≥ 0,8 en el primer candidato; la ficha nunca afirma
   «predecesor» sin órgano coincidente y solapamiento de fechas; el
   resultado declara `metodo ∈ {embedding, fts}` y `n`.
4. **Lotes de primera clase en el contrato.** `GET /licitaciones/{id}`
   devuelve los lotes con importe, CPV y plazo (`LoteOut`); Detalle los pinta;
   el export CSV admite una fila por lote. Esfuerzo S.
   *Aceptación:* DTO tipado; fixture con tres lotes; `exports/download`
   acepta `por_lote=true` y el conteo de filas coincide.

**Verificación:** `make check`; `make audit-truth-check` antes y después de
C1.1 y C1.2 con el delta en la PR. **Riesgo:** alto en C1.2 (columna nueva en
la tabla núcleo y backfill masivo): `plan` antes de `apply`, en ventana.

### C2 — Cuentas y seguridad

**Objetivo:** que el usuario vea y gobierne sus sesiones y claves, que una
organización pueda cambiar de manos o cerrarse, y que lo que falla en el
navegador llegue a alguien.

1. **Sesiones visibles y revocables una a una.** `GET /me/sessions` y
   `DELETE /me/sessions/{id}` sobre `list_active_sessions`, con sesión
   reciente; vista en Ajustes (C7.5). Esfuerzo S.
   *Aceptación:* revocar una sesión no toca las demás (test); la sesión actual
   viene marcada; el listado no expone el token ni el hash.
2. **Ciclo de vida de la organización.** Traspaso de owner en dos pasos
   (propuesta y aceptación), salida voluntaria de un miembro y borrado de
   organización por el owner con confirmación literal; los datos corporativos
   (oportunidades, comentarios, capacidades) se borran o se anonimizan según
   lo que fije el ADR-030 de v2; todo auditado. Esfuerzo M.
   *Aceptación:* tests de cada transición y de sus rechazos; una organización
   con oportunidades abiertas exige confirmación explícita; `audit_log`
   registra actor y objetivo sin copiar emails; la organización personal no
   se puede borrar ni traspasar.
3. **API keys con autoservicio y tiers (D25).** `POST /me/keys` con scopes
   acotados a los del rol y TTL ≤ `API_KEY_MAX_TTL_DAYS`;
   `POST /organizations/{id}/keys` para owner/admin con
   `api_keys.organization_id`; `RateLimitMiddleware` aplica el tier de la
   key. Esfuerzo M · **[§6]** migración, pre-autorizada.
   *Aceptación:* una key `standard` recibe 429 al límite de su tier (test);
   el secreto se muestra una sola vez; la rotación conserva scopes y tier; la
   matriz de scopes de `docs/api-design.md` se genera desde `api/scopes.py`
   (`scripts/gen_scopes_doc.py --check` en CI).
4. **Webhooks con reintento y re-entrega.** Backoff exponencial de un minuto
   a seis horas, seis intentos, sobre la cola de v2 S5;
   `POST /webhooks/{id}/deliveries/{delivery_id}/redeliver`;
   auto-desactivación solo tras agotar reintentos. Esfuerzo M.
   *Aceptación:* un endpoint que falla tres veces y responde 200 a la cuarta
   deja la entrega en `delivered` y `failure_count` en 0 (test); el
   identificador `X-Webhook-Delivery` es estable entre reintentos; la firma
   se recalcula sobre el mismo cuerpo.
5. **Vulnerabilidades con plazo.** Política en `docs/SECURITY.md` (alta ≤ 7
   días, moderada ≤ 30) y triaje de los tres avisos abiertos y de los 37
   fantasma. Esfuerzo S · acción del mantenedor para el triaje.
   *Aceptación:* `security.yml` verde; cero avisos altos abiertos más de
   siete días (medido en la pestaña de seguridad, con fecha); el ítem P3 del
   backlog pasa a Cerrados.
6. **Errores de cliente con vista (D26).** Tabla `client_errors` (huella sin
   PII, ruta, mensaje truncado, versión de build, contador de ocurrencias),
   vista en `/ops` → Observabilidad, retención 30 días. Esfuerzo S · **[§6]**
   migración, pre-autorizada.
   *Aceptación:* un error simulado en E2E aparece en la vista; la fila no
   contiene IP ni email (test); `retention_cleanup` la purga y lo cuenta.
7. **Preferencias de notificación.** Tabla
   `notification_preferences(user_id, organization_id, tipo, canal,
   frecuencia)`, `GET/PUT /me/notification-preferences`, sección en Ajustes
   (C7.5). Es la base que v2 S4.6 necesita. Esfuerzo S · **[§6]** migración,
   pre-autorizada.
   *Aceptación:* contrato tipado; valores por defecto documentados en el DTO;
   el despachador de v2 S4.1 respeta la preferencia (test compartido con v2).
8. **CSP sin `unsafe-inline` en estilos.** Nonce o hash para los estilos que
   Tailwind 4 emite en runtime. Esfuerzo S.
   *Aceptación:* la cabecera CSP de producción no contiene
   `'unsafe-inline'` en `style-src`; `csp-report` sin violaciones nuevas en
   siete días.
9. **Presupuesto de `/ask` por organización.** Cubo por `organization_id`
   además del de usuario (`LLM_BUDGET_USD_DAILY_PER_ORG`). Esfuerzo S ·
   **[§6]** `.env.example`, pre-autorizado.
   *Aceptación:* dos usuarios de la misma organización comparten el
   presupuesto (test con proveedor simulado); el 429 dice qué cubo se agotó.

**Verificación:** `make check`; `make fuzz-api` sin 5xx en las rutas nuevas;
E2E de revocar una sesión y de crear una key. **Riesgo:** medio en C2.2
(borra datos corporativos; confirmación literal y auditoría son la red).

### C3 — Plataforma, coste y rendimiento

**Objetivo:** que la API cargue solo lo que sirve, que un SLO sin alerta deje
de existir, y que el coste sea un número con dueño.

1. **Imagen de la API sin ML** (backlog P2). `requirements-api.in` y
   `requirements-pipeline.in`; `docker/Dockerfile.api` instala solo la API;
   los extras `[ml]` y `[pliegos]` van al pipeline. Esfuerzo M · **[§6]**
   dependencias y Dockerfile, pre-autorizados.
   *Aceptación:* tamaño de imagen medido en `docker-build` y ≤ 60 % del
   actual; `make check-requirements-sync` cubre los dos ficheros; la API
   arranca sin `sentence_transformers` instalado (test de import).
2. **Agregados sin pandas de tabla completa.** Los caminos que quedan en
   `services/analytics/*` migran a SQL; el escáner AST de S4.2 del plan de
   septiembre se extiende a todos los routers de analítica. Esfuerzo M.
   *Aceptación:* `process_resident_memory_bytes` de la API por debajo de 1 GiB
   durante el smoke (medido en `/metrics`); ningún método de
   `db/repositories/*` alcanzable desde `api/routes/analytics.py` devuelve
   `rows_to_dicts` sin `LIMIT`.
3. **Alertas de latencia (SLO 3 y 6).** Reglas `ApiLatencyP99High` sobre
   `http_request_duration_seconds` y `PublicSurfaceSlow` sobre el smoke;
   alerta de RUM en Vercel como acción humana. Esfuerzo S.
   *Aceptación:* reglas con `for: 10m` en `alert_rules.yml`; una latencia
   inyectada en preview dispara la alerta; `docs/sli-slo.md` marca los dos SLO
   como medidos y alertados, con fecha.
4. **Suite más rápida** (backlog P2). Un schema base por sesión y `TRUNCATE`
   por test para las suites de BD; `pytest-xdist` por schema si compensa.
   Esfuerzo M.
   *Aceptación:* `make test-integration` baja al menos un 40 % (medido en CI
   antes y después); un test de fuga entre tests demuestra que el aislamiento
   se conserva.
5. **Preview por PR para la API (D27).** Servicio de preview en Render con
   schema efímero creado por `migrate.yml` en modo `preview` y borrado al
   cerrar la PR. Esfuerzo M · **[§6]** workflow, pre-autorizado; exige v2
   O0.2 cerrado.
   *Aceptación:* cada PR expone una URL con `/health/ready` verde; el schema
   desaparece al cerrar la PR (workflow verificado); el coste mensual queda
   anotado en `docs/COSTES.md`.
6. **Hoja de costes.** `docs/COSTES.md` con Render, Vercel, Supabase, LLM y
   Actions, cifra mensual, umbral de alerta y fecha; `LLM_BUDGET_*`
   referenciados. Esfuerzo S.
   *Aceptación:* documento con fecha; `make status` imprime el presupuesto
   LLM configurado; revisión mensual junto a los SLO.
7. **Peso de `graphify-out/`** (backlog P3). Decidir entre artefacto de CI,
   LFS o conservarlo. Esfuerzo S · decisión del mantenedor.
   *Aceptación:* decisión anotada en AGENTS.md §1 con el tamaño medido.

**Verificación:** `make check`; `docker-build` con tamaño; `make
test-integration` cronometrado. **Riesgo:** medio en C3.1 (una dependencia
que la API necesitaba en runtime y nadie declaró; el test de import la
descubre).

### C4 — Ingesta y calidad del dato

**Objetivo:** que ninguna fuente meta ruido sin decirlo, que las
republicaciones tengan una regla, y que la salud de la ingesta viva en un
sitio.

1. **PSCP acotado (D24).** El conector no persiste avisos sin señal
   tecnológica (título y descripción si el dataset la trae) y cuenta
   descartados en `source_ingestion_health`. Backfill: purgar o marcar
   `analysis_universe = 'pscp_censo'` según lo que decida D24, con delta
   medido. Esfuerzo M.
   *Aceptación:* en el siguiente run, filas nuevas de PSCP con
   `tecnologia IS NULL` = 0; el dataset del clasificador (v2 S6.1) deja de
   contaminarse; `make audit-truth-check` antes y después.
2. **Republicaciones (D23).** Comportamiento único en Radar, listados,
   superficie pública y ficha; ADR-026 registra la regla; el test de literales
   cubre `licitaciones_duplicados` en los cuatro caminos. Esfuerzo S.
   *Aceptación:* un expediente republicado aparece una vez en el Radar y una
   en el sitemap; la ficha enlaza al original; ADR-026 con la regla y fecha.
3. **Euskadi y Galicia por API oficial.** Integración paginada validada
   (`docs/regional-source-coverage.md` la declara pendiente), manteniendo el
   RSS como descubrimiento. Esfuerzo M.
   *Aceptación:* cobertura ≥ 90 % contra una muestra manual de cincuenta
   expedientes por fuente; `REGISTERED_SOURCES` con SLA propio para la API;
   el doc de cobertura actualizado con fecha.
4. **Fechas imposibles** (backlog P3). Corte en el conector con log y
   contador. Esfuerzo S.
   *Aceptación:* `audit_domain_truth` cuenta 0 adjudicaciones con fecha
   anterior a 1990; el contador aparece en el resumen del run.
5. **Umbrales calibrados de `audit_domain_truth`** (backlog P2). Cada umbral
   con valor medido, margen y fecha en el propio script. Esfuerzo S.
   *Aceptación:* el script falla ante una regresión del 10 % sobre el valor
   calibrado; la tabla de umbrales se imprime con `--explain`.
6. **Cuatro tablas de salud a dos.** `extracciones` se retira (o se
   consolida en `extraction_runs`) y `source_ingestion_health` más
   `ops_events` quedan como par «estado actual + historial»; vista de
   compatibilidad durante una ola. Esfuerzo M · **[§6]** migración,
   pre-autorizada.
   *Aceptación:* `scheduler/healthcheck.py` responde cada pregunta desde un
   solo sitio; los runbooks que citan `extracciones` se actualizan; ningún
   test escribe en la tabla retirada.
7. **Completitud de adjudicaciones por fuente.** Métricas de
   `n_ofertas_recibidas`, `oferta_minima`, `oferta_maxima` y `es_pyme` por
   fuente en `/analytics/quality`. Esfuerzo S.
   *Aceptación:* la vista Calidad muestra el porcentaje por campo y fuente con
   fecha; alerta si cae diez puntos respecto a la semana anterior.

**Verificación:** `make check`; `make job-parity`; un run de `scrape-daily`
con los contadores nuevos en su resumen. **Riesgo:** medio en C4.1 (cambia el
corpus; el delta medido y la marca de universo evitan perder datos).

### C5 — Conocimiento: RAG, ficha y diccionario

**Objetivo:** que cada respuesta del asistente diga de dónde sale, que la
ficha tenga con qué medirse, y que el diccionario deje de ser un deploy.

1. **Golden set de extracción de fichas** (backlog P2). Cuarenta pliegos con
   hechos esperados por familia; `services/ml_eval.py` gana `eval_fact_sheet`
   con precisión y recobrado por familia y ratchet. Esfuerzo M (etiquetado
   humano incluido).
   *Aceptación:* fixture versionada en `tests/fixtures/golden_fichas/`;
   `make eval-llm` imprime la tabla; ratchet inicial igual al valor medido y
   solo sube.
2. **Un solo selector de páginas** (backlog P2). La ficha usa el retrieval
   pgvector con los términos como consulta y `_TOPIC_TERMS`/`_TECH_TERMS`
   dejan de ser un selector paralelo. Esfuerzo S; depende de C5.1.
   *Aceptación:* `eval_fact_sheet` no baja; el tiempo de extracción no sube
   más de un 20 % (medido en `pliegos.yml`).
3. **Citas estructuradas en `/ask` (D29).** Evento SSE `sources` con
   `documento_id`, `page_number` y cita; el prompt exige referencia por
   afirmación en modo `licitacion`; la UI enlaza cada cita a su página.
   Esfuerzo M.
   *Aceptación:* en `eval_rag_generation`, al menos el 90 % de las respuestas
   en modo licitación traen una fuente válida (existe en `documento_pages`);
   una respuesta sin fuentes se marca «sin fuentes en el pliego» y la UI lo
   pinta distinto; el campo es aditivo al stream, no al DTO.
4. **Feedback del asistente persistido.** Tabla `asistente_feedback` (hash de
   la pregunta, modo, modelo, voto, motivo opcional; el texto solo con opt-in
   explícito), panel en `/ops` → Active learning. Esfuerzo S · **[§6]**
   migración, pre-autorizada.
   *Aceptación:* el voto aparece en el panel; la fila no contiene PII (test);
   `eval_rag_generation` puede reutilizar las preguntas con opt-in.
5. **Caché de respuestas del LLM.** Clave por modo, modelo, versión de
   prompt y hash de contexto, TTL 24 h, en `shared/cache.py`. Esfuerzo S.
   *Aceptación:* la segunda pregunta idéntica sobre el mismo expediente no
   consume presupuesto (test con proveedor simulado); `llm_cache_hit_total`
   en `/metrics`; `force=true` la salta.
6. **Diccionario de tecnologías como dato (D28).** Tabla
   `tecnologias_keywords` versionada y editable desde `/ops`;
   `filter_version` pasa a ser el hash del contenido; `config/keywords.py`
   queda como semilla; preview de impacto («esta keyword añadiría N
   expedientes de los últimos 90 días») antes de aplicar. Coordina con v2 T3.
   Esfuerzo L · **[§6]** migración, pre-autorizada.
   *Aceptación:* cambiar una keyword no requiere deploy y cambia
   `filter_version` en el linaje de las filas nuevas; un test comprueba que
   la semilla y la tabla coinciden en un arranque limpio; cada cambio queda en
   `audit_log` con el delta de expedientes.
7. **Versión de embeddings y re-embedding.** `documento_chunks.embedding_model`
   y `embedding_version`; job de re-embedding por versión con índice dual;
   `EMBEDDING_VERSION` se usa de verdad o se borra. Esfuerzo M · **[§6]**
   migración, pre-autorizada.
   *Aceptación:* cambiar el modelo no rompe el retrieval (test de fallback a
   la versión anterior); `documentos_embeddings` reporta pendientes por
   versión; `config/settings.py` no declara variables que nadie lee (test de
   uso, extensible a `check_env_parity`).
8. **Clusters y proyectos: decisión por uso.** Sesenta días de telemetría de
   «vista experimental abierta» (v2 S7.3) y después promover a core o retirar
   por RFC. Esfuerzo S · decisión con dato.
   *Aceptación:* decisión escrita con la cifra y la fecha en el backlog.

**Verificación:** `make check`; `make eval-llm` con las dos tablas nuevas;
`pliegos.yml` verde. **Riesgo:** medio en C5.6 (toca la definición de
tecnología; el preview de impacto y el linaje son la red).

### C6 — Colaboración y captura

**Objetivo:** que la oportunidad sea un espacio de trabajo y no una ficha.

1. **Tareas de la oportunidad.** `pursuit_tasks(id, pursuit_id, titulo,
   responsable, vence, estado)`; `next_action` se mantiene como «siguiente
   tarea» derivada. Esfuerzo M · **[§6]** migración, pre-autorizada.
   *Aceptación:* la agenda de Mi Pipeline lista tareas por urgencia; el ICS
   incluye tareas con fecha; evento `pursuit.task_due` en el outbox de v2
   S4.1; una tarea de otra organización no es visible (test).
2. **Menciones en comentarios.** `@nombre` resuelto contra miembros activos;
   notificación al mencionado por el outbox. Esfuerzo S.
   *Aceptación:* test de parseo con nombres ambiguos; sin notificación fuera
   de la organización; el comentario guarda los `user_id` mencionados, no el
   texto resuelto.
3. **Adjuntos propios** (depende de v2 S8.1). La propuesta y sus borradores
   suben al bucket con `organization_id`; listado en la pestaña Expediente;
   descarga firmada con caducidad; dato corporativo a efectos GDPR. Esfuerzo
   M.
   *Aceptación:* límite de tamaño y de tipos; un enlace caducado devuelve
   403; el RAG no indexa adjuntos propios salvo opt-in por adjunto.
4. **Plantilla de go/no-go ponderada (D30).** Cinco criterios (encaje
   estratégico, capacidad, competencia, rentabilidad, riesgo) con pesos por
   organización, puntuación de uno a cinco y umbral; complementa el checklist
   de v2 S2.3. Esfuerzo M · **[§6]** migración, pre-autorizada.
   *Aceptación:* la decisión `go | no_go` puede vincularse a una puntuación;
   `make product-status` imprime «go por debajo del umbral» como métrica; los
   pesos son de owner/admin y quedan auditados.
5. **Mi baja frente al mercado.** Con `offer_price_eur` y el presupuesto, la
   baja propia por CPV a cuatro dígitos y por órgano frente a
   `bajas/referencia`, en Mi Pipeline → Embudo. Esfuerzo S.
   *Aceptación:* requiere al menos cinco ofertas presentadas por segmento y
   declara `n`; usa solo importes de base sin IVA (C1.1).
6. **Notas en seguimientos.** Campo `nota` en favoritos hoy y en `follows`
   cuando llegue v2 T1. Esfuerzo S · **[§6]** migración, pre-autorizada.
   *Aceptación:* contrato tipado; el export GDPR incluye las notas; la nota no
   se muestra a otra organización aunque el favorito sea compartido (test).
7. **Exportar el pipeline.** CSV y Excel de oportunidades con los filtros del
   tablero, con la sanitización de fórmulas de `services/exports.py`.
   Esfuerzo S.
   *Aceptación:* `exports/download?recurso=pursuits`; test de inyección de
   fórmula; el fichero declara organización y fecha en la cabecera.

**Verificación:** `make check`; E2E que crea una tarea, menciona a un
miembro y exporta el tablero. **Riesgo:** bajo.

### C7 — Frontend y accesibilidad

**Objetivo:** que la accesibilidad sea un gate sin excepciones, que el
usuario tenga un solo sitio de ajustes, y que el peso del bundle sea un
número que solo baja.

1. **Remediación axe.** Las cuatro reglas salen de `disableRules` una a una,
   empezando por `nested-interactive`; los cuatro `test.fixme` se resuelven o
   se borran con OK explícito (**[§6]** borrar tests). Esfuerzo M.
   *Aceptación:* `disableRules([])`; `grep -rc test.fixme web/e2e` = 0;
   «Seguir» en el Radar funciona con teclado y lector de pantalla (E2E).
2. **S5.8 del plan de septiembre.** Piso de cobertura de `src/app/**` al
   valor medido y axe sobre `/`, `/licitaciones`, `/cpv` y una ficha pública.
   Esfuerzo S.
   *Aceptación:* las de aquel ítem; el piso solo sube.
3. **Primer uso** (backlog P2). Explicación de la barra de ámbito y estados
   vacíos que enseñan la acción siguiente. Esfuerzo S.
   *Aceptación:* un E2E con usuario nuevo y sin datos encuentra tres estados
   vacíos con acción; ninguno inventa cifras.
4. **`title=` a `Tooltip` por olas.** Regla ESLint que prohíbe `title=` en
   JSX salvo `<abbr>` e `<iframe>`, con allowlist de los 152 de hoy que solo
   encoge. Esfuerzo M.
   *Aceptación:* la regla está activa; el conteo baja al menos cincuenta por
   ola; `accessibility.spec.ts` verde en cada ola.
5. **Ajustes en un sitio.** Espacio «Ajustes» con tema, densidad,
   organización activa, preferencias de notificación (C2.7), sesiones (C2.1),
   API keys (C2.3) y datos y cuenta; `/mi-cuenta` y la sección de organización
   de `/mi-perfil` se absorben como vistas (consolidar no elimina). Esfuerzo
   M.
   *Aceptación:* `console-spaces.ts` con el espacio y sus redirects; los
   tests de títulos derivan la lista; E2E de cambiar una preferencia y verla
   persistida tras recargar.
6. **Presupuesto de bundle.** `@next/bundle-analyzer` en CI con umbral de
   First Load JS por ruta que solo baja e informe en la PR. Esfuerzo S ·
   **[§6]** dependencia y `ci.yml`, pre-autorizados.
   *Aceptación:* umbrales versionados; CI falla al superarlos; el informe se
   adjunta al job.
7. **Captura clara en la portada** (backlog P2). Variante `light` y
   `<picture media>`. Esfuerzo S.
   *Aceptación:* `capturas:landing` genera ambas; `visual.spec.ts` cubre los
   dos temas.
8. **Ortografía castellana** (backlog P3). Barrido con lista acordada y
   comprobación en `lib/legal-placeholder.ts` o hermana. Esfuerzo S.
   *Aceptación:* cero coincidencias de la lista en `web/src`.

**Verificación:** `make web-lint`, `make web-typecheck`, `make web-test`,
`make check-frontend-invariants`, E2E en CI. **Riesgo:** medio en C7.5
(mueve superficie autenticada; los redirects y los tests de títulos son la
red).

### C8 — API y contrato

**Objetivo:** que un cambio incompatible no pueda mergearse sin decirlo, y
que el frontend pruebe contra el contrato real.

1. **Política de deprecación.** Documento en `docs/api-design.md` (noventa
   días, cabeceras `Deprecation`, `Sunset` y `Link` al sucesor) y helper
   `deprecate_route()` en `api/errors.py` o vecino. Va con v2 O0.6e.
   Esfuerzo S.
   *Aceptación:* las cuatro rutas deprecadas de v2 emiten `Sunset` con fecha
   (test); el documento enlaza la RFC de retirada.
2. **Detector de cambios breaking.** `oasdiff` (o equivalente en Python) en
   CI comparando `api/openapi.json` de `master` con el de la PR; falla ante
   un cambio breaking sin etiqueta `api-breaking` y RFC enlazada. Esfuerzo S
   · **[§6]** `ci.yml`, pre-autorizado.
   *Aceptación:* una PR que quita un campo falla; una que añade uno pasa; el
   job imprime el diff legible.
3. **Contrato consumidor-proveedor** (Fase 8 del plan de producto).
   `scripts/check_contract_fixtures.py` valida cada fixture JSON que usan los
   tests del frontend contra el esquema OpenAPI de su operación. Esfuerzo M.
   *Aceptación:* un fixture con un campo inexistente falla en CI; cobertura ≥
   80 % de las operaciones que consumen `web/src/hooks`; los fixtures declaran
   su operación en un manifiesto.
4. **Idempotencia en el resto de escrituras de usuario.** `X-Idempotency-Key`
   en favoritos, reglas, empresas vigiladas y descartes, con el mismo
   almacén que pursuits. Esfuerzo S.
   *Aceptación:* test de doble envío por ruta; la clave caduca según
   `IDEMPOTENCY_TTL_SECONDS`.
5. **S4.10 del plan de septiembre.** `Paginated[T]` en `shared/dto.py`,
   adopción por olas y `MAX_PAGE_LIMIT` universal: `/competitive/renovaciones`
   deja de aceptar `le=1000` y `trends` acota rango o expone `freq`. Esfuerzo
   M.
   *Aceptación:* `grep -c "le=1000" api/routes` = 0; el contrato de
   paginación tiene un solo DTO por estilo; `make check-api-contract` verde.

**Verificación:** `make check-api-contract`; el job de C8.2 en verde sobre la
propia PR. **Riesgo:** bajo.

### C9 — Documentación, ADR y proceso

**Objetivo:** que las decisiones de v2 tengan ADR antes de implementarse, y
que un doc que cita una ruta inexistente no pueda mergearse.

1. **ADR que v2 exige.** ADR-027 backbone de eventos (outbox sobre
   `domain_events`); ADR-028 cola de trabajo y worker (revisa ADR-012: un
   plano de cron, un plano de trabajo a demanda); ADR-029 almacén de objetos
   (revisa «texto por página, sin blob store» del plan de producto); ADR-030
   identidad `user_id` y proveedores OIDC; ADR-031 seguimiento unificado;
   ADR-032 semántica del importe y maestro de órganos (C1). Esfuerzo M.
   *Aceptación:* cada ADR `accepted` antes del merge del stream que lo
   implementa; enlazados desde AGENTS.md §7; ADR-012 y ADR-023 marcados como
   parcialmente superseded donde corresponda.
2. **Documentos que el código desmiente, segunda tanda.** README
   (`db/migrations.py`, `scraper/pipeline.py`), `.pre-commit-config.yaml`
   (`dashboard/`), `docs/api-design.md` (rutas inexistentes, FTS5, scopes),
   `docs/c4-architecture.md` (APScheduler → Actions, y el worker cuando
   exista), `docs/AGENT_PLAYBOOK.md` (FAISS). Esfuerzo S.
   *Aceptación:* `tests/test_docs_paths.py` extrae las rutas de fichero
   citadas en README, `api-design.md` y el playbook y comprueba que existen;
   `make check-agent-docs` incluye `docs/api-design.md` y
   `docs/c4-architecture.md`.
3. **Política de retención publicada.** Tabla en `docs/SECURITY.md` (tabla,
   plazo, motivo, comando) generada por `scripts/gen_retention_doc.py` desde
   constantes con nombre; los plazos pasan a `config/settings.py` como
   `RETENTION_*`. Esfuerzo S · **[§6]** `.env.example`, pre-autorizado.
   *Aceptación:* `python scripts/gen_retention_doc.py --check` en CI; ningún
   plazo literal en `scheduler/retention.py` (test); `.env.example` documenta
   los `RETENTION_*`.
4. **Registro de tratamientos y encargo para organizaciones.**
   `docs/legal/registro-tratamientos.md` y anexo de encargo de tratamiento
   para clientes B2B; `/aviso-legal` enlaza; identidad publicada rellenada
   (razón social, NIF, domicilio, buzón). Esfuerzo S · acción del propietario
   para la identidad.
   *Aceptación:* los dos documentos existen con fecha y revisión del
   propietario; `lib/legal-placeholder.ts` no encuentra huecos en
   `/aviso-legal`.
5. **Higiene del backlog automatizada.** `scripts/check_backlog_freshness.py`
   cruza cada ítem abierto con los marcadores «Cerrado» de la cabecera y con
   las revisiones Alembic que cita ya presentes en `db/alembic/versions/`, y
   avisa. Esfuerzo S.
   *Aceptación:* corre dentro de `make check-agent-docs`; cero ítems abiertos
   marcados como cerrados en cabecera tras v2 O0.5.
6. **Estado de los RFC como dato.** `scripts/gen_rfc_index.py` genera en
   `docs/rfc/README.md` la tabla de RFC con `status` y enlace a la evidencia
   de implementación. Esfuerzo S.
   *Aceptación:* `--check` en CI; los cinco RFC del hecho 25 de v2 figuran
   como implementados; un RFC sin `status` falla el check.

**Verificación:** `make check-agent-docs` con los tres scripts nuevos.
**Riesgo:** nulo.

---

## 4. Métricas de cierre del plan

Se consideran cumplidas cuando el comando indicado las reproduce; no se
anotan cifras a mano en este fichero.

| Métrica | Hoy (2026-09-05) | Objetivo | Cómo medir |
|---|---|---|---|
| Filas nuevas con `importe_tipo` nulo | todas (la columna no existe) | 0 | `audit_domain_truth` |
| Expedientes de PLACSP (12 meses) con `organo_id` | 0 % (la columna no existe) | ≥ 95 % | script de C1.2 |
| Expedientes con predecesor propuesto en la ficha | 0 | golden con precisión ≥ 0,8 | `golden_predecesor.jsonl` |
| Reglas axe desactivadas / `test.fixme` | 4 / 4 | 0 / 0 | `accessibility.spec.ts`, grep |
| Apariciones de `title=` en `.tsx` | 152 | 0, por olas de ≥ 50 | regla ESLint de C7.4 |
| Reglas de alerta de latencia | 0 | 2 | `alert_rules.yml` |
| Avisos altos abiertos más de siete días | por medir | 0 | pestaña de seguridad |
| Sesiones revocables una a una | no | sí | `DELETE /me/sessions/{id}` |
| Claves de API creables desde el producto | no | sí, personales y de organización | `POST /me/keys`, `POST /organizations/{id}/keys` |
| Tiers de API key aplicados | 0 | todos | test de 429 por tier |
| Webhooks con reintento | no | sí (6 intentos) | test de C2.4 |
| Feedback del asistente persistido | no | sí | tabla `asistente_feedback` |
| Golden de fichas | 0 | 40 | `tests/fixtures/golden_fichas/` |
| Respuestas de `/ask` en modo licitación con fuente válida | por medir | ≥ 90 % | `eval_rag_generation` |
| Selectores de páginas de la ficha | 2 | 1 | C5.2 |
| Variables de `config/settings.py` que nadie lee | ≥ 1 (`EMBEDDING_VERSION`) | 0 | test de uso de C5.7 |
| Tablas de salud de la ingesta | 4 | 2 | `git ls-files`, migración de C4.6 |
| Filas nuevas de PSCP sin tecnología | por medir | 0 | `source_ingestion_health` |
| Tamaño de la imagen de la API | por medir | ≤ 60 % del actual | job `docker-build` |
| Duración de `make test-integration` | por medir | −40 % | CI |
| Docs que citan rutas inexistentes | 3 ficheros | 0 | `tests/test_docs_paths.py` |
| ADR que v2 exige y no existen | 6 | 0 | `docs/adr/` |
| Peso de `graphify-out/` en el repo | 17 MB | decisión anotada | `du -sh` |

## 5. Lo que NO se hace

- **Backup y restore drill.** Fuera por decisión del mantenedor.
- **Repetir v2 ni el plan de septiembre.** Lo que allí está planificado se
  cita, no se redefine.
- **SSO SAML o SCIM.** Solo OIDC (v2 S1.2); el aprovisionamiento automático
  de usuarios espera a que exista una organización que lo pida.
- **Web push ni app nativa.** Hasta que las preferencias de C2.7 existan y
  haya demanda medida en telemetría.
- **API pública de pago o marketplace de datos.** Las claves de organización
  de C2.3 no son un producto de venta.
- **Reescribir el parser CODICE.** C1.1 y C1.2 añaden campos; el parser
  conserva su estructura.
- **Cambiar el proveedor LLM por defecto.** El canario y el fallback ya
  cubren su retirada; una migración de proveedor es una decisión aparte.
- **Un segundo motor de búsqueda.** Postgres (`tsvector`, `pg_trgm`,
  pgvector) sigue siendo el único; C5 no introduce otro.

## 6. Secuencia y dependencias con v2

1. **C9.1 y C9.2 primero**, junto a la Ola 0 de v2: los ADR deben existir
   antes de que v2 S4, S5, S8, S1 y T1 se implementen, y los docs con rutas
   inexistentes se corrigen con v2 O0.7.
2. **C3, C4, C7 y C8 son libres** tras la Ola 0 de v2; C3.5 exige v2 O0.2 y
   C8.1 va con v2 O0.6e. C4.1 debe aterrizar antes de v2 S6.1 para que el
   clasificador entrene sobre el corpus acotado.
3. **C1 tras v2 O0.1** (schema al día) y en paralelo a v2 S1; C1.2 en
   ventana con `plan` antes de `apply`.
4. **C2** libre salvo C2.4 (cola de v2 S5) y C2.7 (despachador de v2 S4).
5. **C5** tras C4; C5.6 coordina con v2 T3 porque ambos cambian quién escribe
   la tecnología.
6. **C6** tras v2 S3 y S4; C6.3 tras v2 S8.1.
7. **C7.5** tras C2.1, C2.3 y C2.7, para que Ajustes nazca con contenido real
   y no como espacio vacío.

Cada stream cierra con `make check`, `make check-api-contract`, los controles
de frontend que le toquen, la verificación de su migración contra Postgres en
CI, y la actualización del backlog y de `docs/STATUS.md`. Un ítem sin
verificar no se marca hecho.
