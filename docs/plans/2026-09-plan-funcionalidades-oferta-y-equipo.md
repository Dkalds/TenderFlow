---
tags: [plan, producto, funcionalidades, multi-agente]
---

# Plan de funcionalidades 2026-09, segunda parte — la oferta, el equipo y lo aprendido

Cuarto plan de la serie de septiembre y segundo centrado en funcionalidades.
[v2](2026-09-plan-arquitectura-v2.md) y el
[complementario](2026-09-plan-arquitectura-v2-complementario.md) miran la
arquitectura; el [plan de funcionalidades](2026-09-plan-funcionalidades.md)
recorre el trabajo del usuario de punta a punta (descubrir, calificar,
competir, ejecutar, vigilar, configurar). Este entra en los tres sitios donde
ese recorrido se decide de verdad y que el tercero solo roza: **la oferta que
se prepara**, **el equipo que la prepara** y **lo que se aprende al cerrar**.
Antes, cubre lo que hoy falta en los dos extremos de cada oportunidad: lo
que la plataforma sabe de la propia empresa y lo que sabe del comprador.

Redactado el 2026-09-06 sobre el mismo árbol (rama
`claude/app-architecture-review-d3vcog`, base `master` = `17169ce`). Cada
funcionalidad dice qué hay hoy, con referencia, y de qué ítem de los planes
anteriores depende. No repite nada que allí esté planificado: lo cita por su
identificador (S, T, C, F) y no lo redefine.

**Estado: PROPUESTO el 2026-09-06.** Nada de este documento está implementado.
Mismo contrato de ejecución que sus hermanos: un stream por rama y por
agente, este documento como única fuente de alcance y criterios, y los gates
de AGENTS.md §6 marcados **[§6]** salvo lo que D47 pre-autoriza.

## 0. Alcance y método

**Qué cubre.** Veinticinco funcionalidades en cuatro grupos (H1–H4): la
empresa y el comprador, la preparación de la oferta, el equipo y su gobierno,
y el aprendizaje del resultado. Cada una con el mismo esqueleto que el plan
de funcionalidades: para quién es, qué hace, qué hay hoy (verificado), de qué
depende, esfuerzo, gate, criterios de aceptación observables y su métrica de
adopción en el catálogo de `web/src/lib/analytics.ts`, con la regla de ese
fichero: dimensiones categóricas de cardinalidad baja, nunca identificadores
ni texto del usuario.

**Qué queda fuera.** El backup y el restore drill, por decisión del
mantenedor; todo lo que v2, el complementario y el plan de funcionalidades ya
planifican; y lo listado en §6. No añade espacios de consola: cada
funcionalidad vive en un espacio existente o en los dos que el tercer plan
crea (Cuentas, Dirección).

**Prioridad.** Misma escala: **P0** cierra una promesa del producto («dónde
pujar, a qué precio, contra quién»), **P1** quita un daño diario, **P2** quita
fricción acumulada. El orden de entrega está en §5.

**Corrección al tercer plan, registrada.** Su §6 atribuye D16 (cobertura fuera
de PLACSP y TED) al complementario; D16 es de v2 (§3, «Nuevas»). Se corrige
allí en el mismo commit que crea este documento.

**Convenciones.** Esfuerzo **S** / **M** / **L** como en v2. Las cifras llevan
fecha y se vuelven a medir. Un criterio de aceptación que no se pueda
comprobar no entra. Los identificadores de este plan empiezan por H; las
decisiones continúan en D40.

### Por qué estas y no otras

Los tres patrones del plan de funcionalidades siguen valiendo (dato que
existe y no llega, decisión que se captura y no se explota, pregunta sin
respuesta). Este plan añade un cuarto, que es el que más pesa aquí:

4. **Dato que la fuente publica y la plataforma no lee.** Los informes de
   valoración traen las ofertas de todos los licitadores y sus puntos; el
   CODICE trae el sistema de contratación (acuerdo marco, sistema dinámico);
   Hacienda publica el periodo medio de pago de cada entidad. Ninguno entra
   hoy, y los tres cambian la respuesta a «a qué precio» y «contra quién».

Y una regla de selección: ninguna funcionalidad de aquí sustituye al equipo
de ofertas. La plataforma calcula, contrasta, recuerda y enseña; redactar,
decidir y firmar siguen siendo de las personas (D33 del tercer plan).

## 1. Hechos verificados (2026-09-06)

### La empresa y el comprador

1. **La organización no existe en los datos de mercado.** El dossier
   competitivo funciona para cualquier `empresa_id`
   (`services/competitive/mercado.py:464-484`,
   `GET /competitive/empresas/{empresa_id}/perfil`,
   `api/routes/competitive.py:313`), pero `organizations` solo guarda
   `name`, `is_personal`, `personal_owner_user_id`, `created_by_user_id` y
   `settings_json` (`v61_organizations_pursuits.py:57-77`): nada la enlaza
   con una empresa del maestro. La única tasa de éxito es la de las
   oportunidades (`services/pursuits.py:306`).
2. **Solo se conoce al ganador.** `adjudicaciones` guarda `nombre`, `nif`,
   `empresa_id`, `n_ofertas_recibidas`, `oferta_minima` y `oferta_maxima`
   (`baseline002_pg_core_genesis.py:110-125`); no hay tabla de licitadores
   ni de ofertas perdedoras. El primer bloqueador de `WinProbabilityGate`
   es exactamente ese: «faltan ofertas perdedoras»
   (`services/ml/pricing_scenarios.py:38-48`).
3. **El perfil del órgano se queda corto.** `OrganoDetailResult` devuelve
   KPIs (total, importe total y medio, porcentaje adjudicado, lead-time
   mediano), top de adjudicatarios, estacionalidad y top puntuado
   (`services/analytics/organo_detail.py:99-103`); no calcula incumbencia,
   ofertas medias, baja media ni gasto por año, aunque la baja por órgano
   ya existe (`services/competitive/bajas.py:22-27`) y `n_ofertas_recibidas`
   está en cada adjudicación.
4. **Acuerdos marco y sistemas dinámicos no están modelados.** El parser lee
   `cbc:ProcedureCode` y `cbc:UrgencyCode` en crudo
   (`scraper/codice_parser.py:266-292`) y no `cbc:ContractingSystemCode`;
   la única mención de «acuerdo marco» en el código es un aparte de
   docstring (`services/dedupe.py:367`); los fixtures CODICE solo traen
   `ProcedureCode` 1 y 9.
5. **Riesgo de cobro.** Ninguna referencia al periodo medio de pago a
   proveedores en código ni en documentación (cero coincidencias).
6. **La búsqueda no entra en los pliegos.** Investigador y el retrieval de
   `/ask` buscan sobre `licitaciones.search_vector`
   (`db/repositories/licitaciones.py:1041-1042`, `api/routes/ask.py:209-225`);
   `documento_pages` (página y offsets, `v62:62-82`) y `documento_chunks`
   (pgvector) solo alimentan la ficha y el RAG híbrido
   (`db/search_backend.py:331-371`). No hay listado de expedientes por texto
   del pliego.
7. **No hay ingesta a demanda.** Ningún endpoint trae un expediente por URL
   o número (cero coincidencias de `reprocess`, `reingest` o `from_url` en
   `api/routes/`); el enlace a la fuente se pinta desde `url` con etiqueta
   por fuente (`web/src/lib/fuentes.ts:22-28`) y el scraper es por lotes
   cada cuatro horas (`scrape-daily.yml`).

### La oferta

8. **Precio sin coste.** La oportunidad guarda `offer_price_eur`
   (`shared/dto.py:726`, `ck_pursuits_offer_price` en `v61`) y nada más:
   ni costes, ni margen, ni horas.
9. **La ficha no admite hechos humanos.** Trece familias
   (`shared/tender_facts.py:106-123`); cada ítem lleva `confidence` y
   `evidence` (`EvidenceRef` con `documento_id`, `page_number`, `quote` y
   offsets, `:17-27`); no hay marca de origen ni forma de añadir un hecho a
   mano con su cita.
10. **Colaboración parcial.** Comentarios existen (`pursuit_comments`,
    `v97`); tareas y adjuntos no (C6.1 y C6.3 los planifican; cero
    `UploadFile` en el repo y `python-multipart` excluido a propósito,
    `api/routes/publico_solicitudes.py:21-24`).
11. **Versiones de documento sin diff.** La identidad es
    `(licitacion_id, tipo, source_hash)` (`v88`) con tipos `legal`,
    `technical` y `additional` (`scraper/codice_parser.py:165-169`); un hash
    distinto crea otra fila; `licitaciones_history` solo difiere campos
    (`services/contract_events.py:78`), nunca texto.
12. **DEUC.** Cero coincidencias de `deuc` o `espd` fuera de los planes.
13. **Equipo sin personas.** `TeamRequirement(role, minimum_years,
    quantity)` y `CertificationRequirement.scope ∈ {company, team, other}`
    (`shared/tender_facts.py:53-58`, `:90-96`); ninguna tabla de personas;
    S2.2 planifica perfiles agregados por rol.
14. **Esfuerzo de ofertar.** Nada lo estima; el corpus limita a
    `MAX_DOCUMENT_PAGES = 250` (`config/settings.py:384`) y las páginas por
    documento están en `documento_pages`.

### El equipo

15. **Roles solo de organización.** `OrganizationRole = owner | admin |
    member | viewer` (`shared/dto.py:574`) y estados `active | invited |
    suspended | revoked` (`v61:110-117`); no hay ámbito más estrecho que la
    organización ni forma de compartir hacia fuera: el único enlace sin
    sesión es el del calendario ICS (`api/routes/exports.py:274-278`).
16. **Reglas por persona.** `watchlist_rules` lleva `user_key` y, desde
    `v64`, `organization_id` y `visibility` (`db/watchlist.py:16-25`); la
    evaluación escribe en `user_notifications`, encola digest y dispara
    webhooks (`scheduler/watchlist_rules_alerts.py:196-212`, `:313-326`).
    No hay reglas de organización ni asignación automática (cero
    coincidencias).
17. **Decisión sin aprobación.** `PursuitDecision = pending | go | no_go`
    (`shared/dto.py:586`) con motivo libre; nadie aprueba nada.
18. **Salud del pipeline a medias.** `next_action` y `next_action_due`
    (`v83`), urgencias `vencida | hoy | semana | mes | despues | sin_fecha`
    (`shared/dto.py:915-916`) y `median_decision_time_hours`; el historial
    solo registra `pursuit.created` y `pursuit.updated`
    (`db/repositories/pursuits.py:133`, `:278`) y pinta al actor como
    «Usuario #N» (`web/src/components/pursuits/pursuit-activity.tsx:74-76`).
19. **Triaje de uno en uno.** El Radar navega con `J K`, sigue con `S` y
    descarta con `X` (`web/src/app/(dashboard)/radar/page.tsx:80-85`);
    `radar_dismissals(user_key, id_externo, created_at)` (`v76:75-80`) sin
    motivo ni organización. Detalle tiene barra de selección con comparar
    (2–3), exportar selección (CSV en cliente) y seguir N
    (`web/src/app/(dashboard)/detalle/page.tsx:872-912`); no hay descartar,
    asignar ni etiquetar en lote.
20. **Vistas compartibles que nadie comparte.** La API acepta `visibility`
    y `organization_id` (`api/routes/saved_filters.py:55-60`) y la UI no
    los manda (`web/src/lib/saved-views.ts:72`); vistas y reglas no se
    conocen (ninguna referencia entre `saved_filters` y `watchlist_rules`).
21. **Avisos sin bandeja.** Tipos `rule_match`, `deadline_30/7/1`,
    `renovacion_30/7` (`v48:9-16`), `pursuit_asignada`
    (`services/pursuits.py:129`) y adjudicación detectada
    (`services/pursuit_awards.py:77`); solo la campana, con cinco alertas
    (`web/src/components/notification-bell.tsx:212`); los recordatorios de
    plazo son solo in-app (`services/deadline_reminders.py:26-29`); un
    digest cuyo SMTP falla se marca enviado igual
    (`scheduler/watchlist_alerts.py:355-358`).

### El resultado

22. **Cierre sin puntos.** La oportunidad guarda `outcome`,
    `awarded_amount_eur` y `outcome_reason` (`v61`); la familia
    `award_criteria` tiene `weight_pct` y `criterion_type`
    (`shared/tender_facts.py:39-45`); no hay puntuación por criterio ni
    propia ni ajena.
23. **Los informes de valoración entran y nadie los lee.** La cola de
    descarga prioriza oportunidades, favoritos y tecnología sin filtrar por
    tipo (`db/repositories/documentos.py:260-292`), así que las actas y los
    informes publicados como `additional` se descargan; ninguna extracción
    saca de ellos licitadores ni puntos. Tras la adjudicación solo hay
    estructura en `contrato_eventos` y `resoluciones_recurso` (`v40`).
24. **Exportación.** `csv | excel | pdf` en la API
    (`api/routes/exports.py:125`) y solo `csv | excel` en el desplegable
    (`web/src/components/export-popover.tsx:37`); el ZIP ya se usa en
    `/me/data`.
25. **Presupuesto LLM.** `LLM_BUDGET_USD_DAILY = 5`, mensual 50, por usuario
    1 (`config/settings.py:588-593`); cualquier extracción nueva compite con
    la ficha por ese cubo.

## 2. Decisiones del mantenedor (D40–D47)

Continúa la numeración de los planes anteriores.

| Id | Decisión | Desbloquea |
|---|---|---|
| D40 | **Acuerdos marco.** Un spike de una semana mide, en un mes de entradas ATOM, la cobertura de `cbc:ContractingSystemCode` y de la referencia al expediente padre en los contratos basados. Se modela solo si el código aparece en más de la mitad de los expedientes cuyo procedimiento es «basado»; si no, se queda en la etiqueta legible de F1.7. | H1.3 |
| D41 | **Riesgo de cobro.** El periodo medio de pago a proveedores de Hacienda es un dato abierto por entidad, no un portal de licitaciones, pero sigue siendo una fuente nueva y D16 de v2 las cierra. Propuesta: excepción acotada a ese dato, con conector `advisory` y cruce por DIR3 (C1.2). | H1.4 |
| D42 | **DEUC.** ¿Generar la respuesta DEUC (ESPD Response) desde el perfil de capacidad, o solo un checklist de lo que hay que declarar? Propuesta: generar XML y PDF tras un spike que fije la versión del esquema que acepta el servicio DEUC de PLACSP; sin esa versión confirmada, solo el checklist. | H2.6 |
| D43 | **Motivos de descarte.** Lista cerrada: `importe`, `territorio`, `tecnologia`, `plazo`, `competencia`, `fuera_de_ambito`, `ya_conocida`, `otro`. Propuesta: cerrada, por la misma razón que D37: una lista abierta no se puede agregar ni usar para calibrar. | H3.6, H4.3 |
| D44 | **Invitados externos.** Rol `guest` acotado a oportunidades concretas, invitado por owner o admin, con caducidad de 90 días y sin acceso a nada de la organización fuera de esas oportunidades. Pendiente: si un invitado puede comentar. Propuesta: sí, con sus comentarios marcados como externos. | H3.2 |
| D45 | **Cuadro de ofertas.** Extraer con LLM las tablas de ofertas y puntos de los informes de valoración cuesta presupuesto (hecho 25). ¿Ámbito: solo expedientes seguidos o con oportunidad, o todo el ámbito de mercado de la organización (F6.1)? Propuesta: seguidos y con oportunidad primero, y el ámbito completo cuando el spike diga cuánto cuesta por expediente. | H4.2 |
| D46 | **Personas del equipo.** Guardar personas nombradas de la organización (rol, años, certificaciones, coste/hora opcional) es dato personal de empleados. Propuesta: sí, con campos mínimos, finalidad declarada en la UI, borrado por owner/admin y desactivado por defecto hasta que la organización lo active. | H3.1, H2.1 |
| D47 | **Gates §6 pre-autorizados para este plan.** Migraciones de H1.3, H1.5 (solo índice), H1.6, H2.1, H2.3, H2.4, H2.5, H2.7, H3.1, H3.2, H3.3, H3.6, H3.7, H4.1 y H4.2 en los términos de cada ítem; `.env.example` para `PMP_SOURCE_URL` (H1.4). Ninguna edición de workflows y ninguna dependencia nueva: el diff usa `difflib`, el XML y el ZIP la biblioteca estándar, y el PDF `reportlab`, que ya está. | todos |

Mientras D40–D46 no estén cerradas, los ítems que las citan no se empiezan.

---

## 3. Funcionalidades por grupo

Cada ítem: **Para quién** · **Qué** · **Hoy** · **Depende de** · **Esfuerzo /
gate** · **Aceptación** · **Adopción** (evento o propiedad del catálogo).

### H1 — La empresa y el comprador

#### H1.1 Mi empresa en los datos — P0

**Para quién.** Owner, admin y quien vende. **Qué.** Pestaña «Mi empresa»
en Equipo: el dossier público de la organización (reutiliza el perfil
competitivo sobre el `empresa_id` que S2.1 enlaza por NIF), «importar como
referencias» (cada adjudicación propia pasa a referencia de S2.2 con órgano,
importe, año, expediente y la tecnología que la plataforma le asignó),
órganos donde ya hemos ganado y rivales encontrados (otros adjudicatarios de
esos órganos y CPV). Declara que la tasa de éxito pública no se puede
calcular sin ofertas perdedoras, hasta H4.2. **Hoy.** Hecho 1. **Depende
de.** NIF de la organización (v2 S2.1) y perfil de capacidad (S2.2).
**Esfuerzo / gate.** M · sin gate.

*Aceptación:*
- `GET /organizations/{id}/empresa` devuelve el dossier con `empresa_id` y
  `metodo=nif`, o 404 con motivo `sin_nif` | `nif_sin_adjudicaciones`.
- «Importar referencias» escribe en las capacidades de S2.2 de forma
  idempotente por `(organization_id, licitacion_id)`; el segundo clic no
  duplica (test).
- El dossier declara ventana y universo (ADR-014) y excluye a la propia
  organización de la lista de rivales.
- Test de aislamiento: el `empresa_id` sale del enlace de S2.1, nunca del
  cliente; una organización no puede pedir el dossier de otra.

*Adopción:* evento nuevo `mi_empresa_abierta` con
`resultado ∈ {dossier, sin_nif, sin_datos}`; propiedad `origen=importacion`
en la creación de referencias.

#### H1.2 Perfil del comprador: incumbencia, concurrencia y baja — P1

**Para quién.** Quien decide si vale la pena. **Qué.** `OrganoDetailResult`
gana `incumbencia` (proporción de adjudicaciones al mismo adjudicatario que
la anterior del mismo CPV a cuatro dígitos, 36 meses), `ofertas_medias`,
`baja_media_pct` (la que ya calcula `bajas_agregadas` por órgano),
`gasto_por_anio`, `pct_anulados_desiertos` (comparte cálculo con F1.4),
`procedimientos` (conteo por código, etiqueta de F1.7) y `mi_historial`
(oportunidades de mi organización con ese órgano y su resultado). Se pinta
donde ya está «Competencia esperada» en el inspector del Radar, en la
oportunidad y en la vista de cuenta de F1.5. **Hoy.** Hecho 3. **Depende
de.** Nada; mejora con el maestro de órganos (C1.2). **Esfuerzo / gate.** S
· sin gate.

*Aceptación:*
- Campos aditivos con `n` y ventana; nulos por debajo de cinco
  adjudicaciones (ADR-014).
- `mi_historial` solo con el `organization_id` del contexto y nunca en la
  superficie pública.
- Test con fixture: órgano con el mismo adjudicatario en tres de cuatro
  contratos consecutivos → `incumbencia = 0.75`.
- El cálculo entra en el precómputo de agregados, no en la petición.

*Adopción:* ninguna propia; se mide por `espacio_abierto` con
`vista=cuentas` (F1.5).

#### H1.3 Acuerdos marco, sistemas dinámicos y contratos basados (D40) — P1

**Para quién.** Quien pierde horas en basados de acuerdos marco donde no
está. **Qué.** El parser lee `cbc:ContractingSystemCode` y la referencia al
expediente padre cuando CODICE la trae; columnas `sistema_contratacion ∈
{acuerdo_marco, sda, basado_am, basado_sda, ninguno}` y `expediente_padre`;
la ficha muestra «contrato basado en el acuerdo marco X» con enlace y la
lista de adjudicatarios del acuerdo; el Radar añade el `risk_flag`
`fuera_del_acuerdo_marco` cuando el NIF de la organización (S2.1) no está
entre ellos; las reglas (S4.4) ganan `sistema_contratacion` para «avísame de
un acuerdo marco nuevo en mis CPV». **Hoy.** Hecho 4. **Depende de.** D40
(spike), S2.1 para el flag, F1.7 para las etiquetas. **Esfuerzo / gate.** L ·
**[§6]** migración, pre-autorizada.

*Aceptación:*
- Spike con resultado escrito en `docs/plans/`: muestra de un mes, cobertura
  del código y de la referencia al padre, y decisión.
- Fixture CODICE con un acuerdo marco y un basado; test del parser y del
  enlace al padre.
- `fuera_del_acuerdo_marco` solo si el acuerdo tiene adjudicatarios cargados
  y el NIF no aparece; sin NIF, sin flag y declarado en la explicación de
  F1.3.
- Regla `sistema_contratacion=acuerdo_marco` con preview (F5.5) que
  devuelve el conteo real de los últimos 90 días.

*Adopción:* propiedad `flag=fuera_del_acuerdo_marco` en `radar_triaje`;
`sistema ∈ {acuerdo_marco, sda}` en `regla_creada`.

#### H1.4 Riesgo de cobro del comprador (D41) — P2

**Para quién.** Una pyme que no puede financiar a la administración. **Qué.**
Periodo medio de pago a proveedores de la entidad, del dato abierto mensual
de Hacienda, enlazado por DIR3; en la ficha y en la explicación de F1.3 como
`pmp_dias` con el mes del dato; `risk_flag` `pago_lento` por encima del
umbral (60 días por defecto, configurable) que el perfil puede poner a cero.
**Hoy.** Hecho 5. **Depende de.** D41 y el maestro de órganos con DIR3
(C1.2). **Esfuerzo / gate.** M · **[§6]** `.env.example` (`PMP_SOURCE_URL`),
pre-autorizado; sin dependencia nueva.

*Aceptación:*
- Spike con cifra y fecha: cobertura del cruce DIR3 sobre los órganos con
  expedientes en doce meses; objetivo ≥ 60 %. Sin cruce, sin dato y sin flag.
- Conector en el plano de GitHub Actions (ADR-012), paso `advisory`, cursor
  propio y fila en `source_freshness`.
- La ficha declara mes del dato y ámbito (entidad o grupo consolidado).
- Test: PMP 95 → flag; 40 → sin flag; sin dato → `desconocido`.

*Adopción:* propiedad `flag=pago_lento` en `radar_triaje`.

#### H1.5 Buscar dentro de los pliegos — P0

**Para quién.** Quien vende algo que nunca sale en el título. **Qué.**
Búsqueda de texto sobre `documento_pages`: devuelve expedientes con el
fragmento y la página, combinable con los filtros del listado (F1.1), «ver
en la página» abre el visor (F2.5), y se guarda como vista (H3.7) o como
regla con `texto_pliego` (S4.4) para «avísame cuando un pliego mencione
esto». **Hoy.** Hecho 6. **Depende de.** F1.1 para los filtros; F2.5 para el
visor; S4.4 para la regla. **Esfuerzo / gate.** M · **[§6]** migración (solo
un índice GIN sobre `documento_pages`), pre-autorizada.

*Aceptación:*
- `POST /search/pliegos` con `websearch_to_tsquery('spanish')` y
  `ts_headline`; devuelve `documento_id`, `page_number`, `fragmento` y
  `n_paginas_coincidentes` por expediente.
- Declara universo: «solo expedientes con pliego procesado», con el conteo
  de cuántos del filtro lo tienen (ADR-014).
- p95 < 800 ms sobre el corpus actual, medido con fecha; `EXPLAIN` sin
  recorrido secuencial de `documento_pages`.
- La regla con `texto_pliego` se evalúa solo sobre documentos procesados
  desde la última pasada (cursor), nunca sobre el corpus entero.

*Adopción:* propiedad `ambito=pliegos` en `busqueda_realizada`.

#### H1.6 Resolver un enlace o un número de expediente — P2

**Para quién.** Quien recibe un enlace por correo de un socio o un cliente.
**Qué.** Pegar en ⌘K (F1.2) una URL de PLACSP, TED o PSCP, o un número de
expediente, resuelve al expediente si está ingerido; si no, lo deja en una
cola de «traer cuanto antes» que la siguiente pasada del scraper prioriza,
con aviso al solicitante cuando entra. **Hoy.** Hecho 7. **Depende de.** F1.2;
outbox (S4.1) para el aviso. **Esfuerzo / gate.** M · **[§6]** migración
(`solicitudes_expediente`), pre-autorizada.

*Aceptación:*
- Spike previo, escrito: qué identificador recupera cada fuente por búsqueda
  dirigida sin scraping nuevo; si PLACSP no lo permite, la cola solo
  prioriza dentro del feed y se lo dice al usuario.
- Resolutor con tests por fuente y por número de expediente normalizado;
  ante ambigüedad devuelve lista, nunca adivina.
- Cola con `estado ∈ {pendiente, encontrado, no_encontrado}`, límite por
  usuario y día, y aviso al cambiar de estado.

*Adopción:* propiedades `ambito=enlace` y
`resultado ∈ {encontrado, encolado, no_encontrado}` en `busqueda_realizada`.

### H2 — Preparar la oferta

#### H2.1 Hoja de costes y baja máxima — P0

**Para quién.** Quien fija el precio y responde de él. **Qué.** Por
oportunidad, líneas de coste (perfil, tarifa/hora de la organización, horas;
otros costes; margen objetivo) → coste, precio mínimo y **baja máxima**
sobre el presupuesto base sin IVA (C1.1); el simulador de F2.2 marca esa baja
como límite y enseña los puntos que da. Tarifas por defecto de la
organización en `organization_rate_cards` (owner/admin), editables por
oportunidad. **Hoy.** Hecho 8. **Depende de.** Importe con semántica (C1.1);
F2.2 para el cruce; H3.1, opcional, para cargar personas con coste.
**Esfuerzo / gate.** M · **[§6]** migración (`pursuit_cost_lines`,
`organization_rate_cards`), pre-autorizada.

*Aceptación:*
- DTOs estrictos; `baja_maxima_pct` se calcula en backend y se sella en
  `pursuit_events` (`cost_sheet_updated`) con versión.
- Test: presupuesto 100.000, coste 82.000, margen objetivo 10 % → precio
  mínimo 91.111 y baja máxima 8,9 %.
- Dato corporativo: fuera del export GDPR de usuario; `member` y superiores
  escriben, `viewer` lee.
- Un `offer_price_eur` por debajo del precio mínimo produce un aviso no
  bloqueante, registrado en el historial.

*Adopción:* evento nuevo `hoja_costes_editada` con `primera_vez`.

#### H2.2 Esfuerzo de ofertar — P2

**Para quién.** Quien decide con el calendario delante. **Qué.** Horas
estimadas de preparar la oferta a partir de la ficha: criterios de juicio de
valor, documentos exigidos (F2.3), páginas del pliego, plazo restante y
lotes, con horas por componente que fija la organización; entra como
criterio «rentabilidad» del go/no-go ponderado (C6.4) y como coste de oferta
en H2.1. **Hoy.** Hecho 14. **Depende de.** F2.3 y C6.4. **Esfuerzo / gate.**
S · sin gate.

*Aceptación:*
- `GET /pursuits/{id}/esfuerzo` con desglose por componente y `n` de
  criterios; sin ficha, `desconocido`.
- Horas por componente editables por owner/admin, con valores por defecto
  documentados en el DTO; se presenta como estimación, nunca como medida.
- Test con fixture: tres criterios de juicio y seis documentos → horas según
  la plantilla.

*Adopción:* ninguna propia; `hoja_costes_editada` gana `con_esfuerzo`.

#### H2.3 Subrayados del equipo y hechos manuales — P1

**Para quién.** Quien lee el pliego y encuentra lo que el extractor no vio.
**Qué.** En el visor (F2.5), seleccionar texto y guardar un subrayado con
nota, visible para la organización; «convertir en hecho» añade un ítem a la
familia elegida de la ficha con `origin=manual`, `EvidenceRef` real
(documento, página, offsets) y autor; los hechos manuales sobreviven a la
re-extracción y se distinguen en la UI. **Hoy.** Hecho 9. **Depende de.**
Visor de página (F2.5). **Esfuerzo / gate.** M · **[§6]** migración
(`document_highlights`; `origin` en los ítems de la ficha), pre-autorizada.

*Aceptación:*
- Anclaje por `(documento_id, page_number, start_offset, end_offset)` más
  hash del texto; si el documento cambia de versión (H2.5) el subrayado pasa
  a `desanclado`, no se pierde.
- Un hecho manual lleva `origin=manual` y no cuenta como acierto del
  extractor en `eval_fact_sheet` (C5.1).
- Aislamiento por organización (test); el export GDPR incluye los subrayados
  propios.

*Adopción:* evento nuevo `subrayado_creado` con `convertido_en_hecho`.

#### H2.4 Consultas al órgano — P2

**Para quién.** Quien tiene dudas y un plazo para preguntarlas. **Qué.**
Lista de consultas del equipo por oportunidad (borrador → enviada →
respondida), con el plazo de consultas de `critical_deadlines` cuando la
ficha lo trae; la respuesta se enlaza al documento publicado (F5.1);
recordatorio dos días antes del cierre de consultas. **Hoy.** No existe.
**Depende de.** Tareas (C6.1), del mismo patrón; F5.1. **Esfuerzo / gate.** S
· **[§6]** migración (`pursuit_questions`), pre-autorizada.

*Aceptación:*
- Estados con transiciones y test; una consulta respondida guarda
  `documento_id`.
- Recordatorio por el outbox con la preferencia de C2.7; sin plazo detectado,
  sin recordatorio, y la UI lo dice.

*Adopción:* evento nuevo `consulta_registrada` con `estado`.

#### H2.5 Qué cambió en el pliego — P1

**Para quién.** Quien ya leyó la versión anterior. **Qué.** Cuando un
expediente seguido publica un documento del mismo `tipo` con otro
`source_hash`, se conserva la versión anterior y se calcula el diff por
página (`difflib`) con resumen «N párrafos cambiados en las páginas X»;
evento `licitacion.documento_modificado`; la pestaña Pliegos muestra
versiones y diff, y el aviso de corrección de F5.3 enlaza aquí. **Hoy.**
Hecho 11. **Depende de.** Documentos nuevos (F5.1). **Esfuerzo / gate.** M ·
**[§6]** migración (`documentos.version`, `documentos.replaces_id`),
pre-autorizada.

*Aceptación:*
- Test: dos versiones con un párrafo cambiado → diff con esa página;
  versiones con el mismo hash → sin evento.
- Diff calculado una vez y cacheado; documentos por encima de
  `MAX_DOCUMENT_PAGES` → resumen sin diff, declarado.
- El evento solo para expedientes seguidos u oportunidades abiertas (misma
  regla que S4.5).

*Adopción:* propiedad `tipo=documento_modificado` en la lectura de alertas.

#### H2.6 DEUC prellenado (D42) — P1

**Para quién.** Quien rellena el mismo formulario en cada oferta. **Qué.**
Generar la respuesta DEUC desde la identidad fiscal (S2.1) y el perfil de
capacidad (S2.2): parte II (empresa), parte III (declaraciones por defecto)
y parte IV (criterios de selección cuando el pliego los exige: cifra de
negocio, referencias, certificaciones), en XML y PDF, con revisión campo a
campo. **Hoy.** Hecho 12. **Depende de.** D42 (spike), S2.1, S2.2. **Esfuerzo
/ gate.** M · sin gate (XML con la biblioteca estándar, PDF con `reportlab`).

*Aceptación:*
- Spike escrito: versión del esquema que acepta el servicio DEUC de PLACSP y
  si la petición DEUC viene entre los documentos del expediente.
- XML validado contra el esquema fijado en el spike (fixture); los campos
  sin dato quedan vacíos y marcados, nunca inventados.
- Test: perfil con dos certificaciones y tres ejercicios → aparecen en la
  parte IV.

*Adopción:* propiedad `recurso=deuc` en `export_lanzado`.

#### H2.7 Biblioteca de respuestas — P1

**Para quién.** Quien vuelve a escribir lo que ya escribió. **Qué.** Buscar y
preguntar sobre las ofertas anteriores de la organización (adjuntos con
opt-in de C6.3) en un modo `biblioteca` del asistente, aislado por
organización; «fragmentos» guardados (texto, etiquetas, oferta de origen,
fecha) reutilizables desde el guion de F2.6. **Hoy.** Hecho 10. **Depende
de.** Adjuntos propios (C6.3), bucket (S8.1), citas (C5.3). **Esfuerzo /
gate.** L · **[§6]** migración (`organization_snippets`; embeddings de
adjuntos con `organization_id`), pre-autorizada.

*Aceptación:*
- Retrieval con filtro `organization_id` en SQL; test de aislamiento en las
  dos dimensiones; nunca mezcla con el corpus público salvo petición
  explícita en la misma consulta.
- Aplica el presupuesto por organización (C2.9).
- Cada respuesta cita adjunto y página (C5.3); sin adjuntos indexados, el
  modo lo dice en vez de responder.

*Adopción:* `modo=biblioteca` en `asistente_usado`; evento nuevo
`fragmento_guardado`.

#### H2.8 Dossier de la oportunidad — P2

**Para quién.** Quien lleva la oportunidad a un comité o a un socio. **Qué.**
ZIP con la ficha en PDF (F2.7), los pliegos descargados, los adjuntos propios
(C6.3), la hoja de costes (H2.1) y los comentarios; y el PDF entra en el
desplegable de exportación, que hoy no lo ofrece. **Hoy.** Hecho 24.
**Depende de.** F2.7 y C6.3. **Esfuerzo / gate.** S · sin gate (`zipfile`).

*Aceptación:*
- `GET /pursuits/{id}/dossier` en streaming, con límite de tamaño declarado
  y nombres de fichero saneados.
- Test de aislamiento; un `viewer` descarga y un invitado (H3.2) solo el de
  sus oportunidades.
- `export-popover.tsx` ofrece `pdf`.

*Adopción:* `recurso=dossier` en `export_lanzado`.

### H3 — El equipo y su gobierno

#### H3.1 Equipo adscrito y disponibilidad (D46) — P1

**Para quién.** Quien promete un equipo en cada oferta y luego tiene que
cumplirlo. **Qué.** Personas de la organización (nombre, rol, años,
certificaciones, coste/hora opcional), adscripción por oportunidad (rol
exigido ↔ persona, dedicación, fechas) y por contrato en cartera (F4.3);
«disponibilidad» cruza compromisos y avisa de solapes; el checklist de S2.3
contrasta `team_requirements` contra personas nombradas y no solo contra
conteos. **Hoy.** Hecho 13. **Depende de.** D46, S2.2, F4.3; H2.1 para el
coste. **Esfuerzo / gate.** L · **[§6]** migración (`organization_people`,
`pursuit_staffing`), pre-autorizada.

*Aceptación:*
- Campos mínimos y finalidad declarada en la UI; dato corporativo: el owner o
  admin borra a una persona y sus adscripciones históricas se anonimizan
  (test); nunca en telemetría ni en la superficie pública.
- `GET /pursuits/{id}/staffing` con veredicto por requisito
  `cubierto | parcial | sin_cubrir` y la evidencia de la ficha.
- Test: dos oportunidades con la misma persona al 80 % en fechas solapadas
  → aviso de solape.
- Desactivado por defecto: la organización lo activa en Ajustes y hasta
  entonces no existe la pestaña.

*Adopción:* evento nuevo `adscripcion_editada` con `primera_vez`.

#### H3.2 Invitado externo por oportunidad (D44) — P1

**Para quién.** Una UTE, un subcontratista, un asesor. **Qué.** Invitar por
email (S1.1) a alguien de fuera con rol `guest` sobre una o varias
oportunidades: ve expediente, ficha, pliegos, tareas asignadas y los
comentarios marcados como visibles para invitados; no ve Radar, pipeline ni
nada de la organización; caduca a los 90 días y se revoca desde la
oportunidad. **Hoy.** Hecho 15. **Depende de.** D44, invitaciones (S1.1),
tareas (C6.1). **Esfuerzo / gate.** M · **[§6]** migración (`pursuit_guests`),
pre-autorizada.

*Aceptación:*
- `require_organization` no concede nada a un `guest`; un
  `require_pursuit_access` nuevo resuelve miembro o invitado y se aplica en
  cada ruta de oportunidad, con test por ruta y `make fuzz-api` sin 5xx.
- Comentarios: campo `visible_invitados` por comentario, falso por defecto;
  un invitado nunca lee comentarios anteriores a su invitación salvo los
  marcados.
- Invitación, acceso y revocación en `audit_log`; el export GDPR del
  invitado incluye su invitación y su borrado la anonimiza.

*Adopción:* evento nuevo `invitado_externo` con `primera_vez`.

#### H3.3 Enrutado de oportunidades por reglas de organización — P2

**Para quién.** Una organización con territorios o líneas repartidas.
**Qué.** Reglas de organización (owner/admin) con las condiciones de S4.4 y
una acción: notificar a un miembro, o crear la oportunidad en `identified`
asignada a él con `next_action` «calificar»; evaluadas en el mismo job que
las reglas personales y con la vista previa de F5.5. **Hoy.** Hecho 16.
**Depende de.** Reglas más ricas (S4.4), ámbito de la organización (F6.1).
**Esfuerzo / gate.** M · **[§6]** migración (`organization_routing_rules`),
pre-autorizada.

*Aceptación:*
- Idempotente por `(regla, id_externo)`; la unicidad
  `(organization_id, licitacion_id)` de `pursuits` evita duplicados cuando
  dos reglas casan: la segunda solo notifica (test).
- Un miembro revocado deja de recibir; la regla queda `sin_destinatario` y
  la UI lo dice.
- Test de paridad entre vista previa y ejecución, como en S4.4.

*Adopción:* `tipo=organizacion` en `regla_creada`; `origen=enrutado` en
`pursuit_creado`.

#### H3.4 Aprobación de go por umbral — P2

**Para quién.** Dirección, cuando la oferta compromete de verdad. **Qué.**
`OrganizationSettings` gana `go_aprobacion_desde_eur` y el rol aprobador;
un `decision=go` sobre un presupuesto igual o mayor queda
`go_pendiente_aprobacion` hasta que un aprobador confirma o devuelve con
motivo; visible en el tablero y en el cuadro de mando de F4.2. **Hoy.**
Hecho 17. **Depende de.** La puntuación de C6.4 acompaña la solicitud cuando
exista. **Esfuerzo / gate.** S · sin gate (`settings_json` y
`pursuit_events`).

*Aceptación:*
- Transiciones con test; un `member` no aprueba; quien solicita no se
  aprueba a sí mismo.
- Sin umbral configurado nada cambia (test de regresión sobre el flujo
  actual).
- Eventos `go_solicitado`, `go_aprobado` y `go_devuelto` en `pursuit_events`
  y en el outbox (aviso al aprobador).

*Adopción:* propiedad `estado=go_pendiente_aprobacion` en
`pursuit_estado_cambiado`.

#### H3.5 Salud del pipeline — P1

**Para quién.** Quien coordina y no puede abrir cada oportunidad. **Qué.**
Banderas por oportunidad calculadas en backend: `sin_responsable`,
`sin_proxima_accion`, `accion_vencida`, `sin_actividad_14d`,
`decision_pendiente_a_5_dias_del_cierre`, `presentada_sin_resultado_90d`;
filtro «necesita atención» en el tablero, KPI en F4.2 y aviso semanal al
responsable; el historial muestra el nombre del actor en lugar de
«Usuario #N». **Hoy.** Hecho 18. **Depende de.** Nada; F4.2 lo pinta.
**Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- `PursuitSummary.salud: list[str]` aditivo, con catálogo cerrado y test por
  bandera.
- `PursuitEventOut.actor_name` aditivo, resuelto en la consulta, nunca el
  email.
- `GET /pursuits/metrics` gana `necesitan_atencion` con `n`.
- El aviso semanal respeta C2.7 y no sale si no hay banderas.

*Adopción:* propiedad `filtro=atencion` en `espacio_abierto`.

#### H3.6 Triaje en lote y con motivo (D43) — P1

**Para quién.** Quien tría cincuenta expedientes cada mañana. **Qué.** En el
Radar, selección múltiple con teclado (`⇧J`/`⇧K`, `⌘A` sobre la página) y
acciones en lote: descartar con motivo (lista cerrada, D43), seguir, asignar
a un miembro (crea oportunidades asignadas) y etiquetar (F1.6); descartes
visibles para la organización con autor y motivo; los motivos alimentan la
calibración de S3.3 y la explicación de F1.3. **Hoy.** Hecho 19. **Depende
de.** Seguimiento unificado (T1) para la visibilidad; hasta entonces,
columnas en `radar_dismissals`; etiquetas (F1.6). **Esfuerzo / gate.** M ·
**[§6]** migración (`radar_dismissals.motivo`, `.organization_id`),
pre-autorizada.

*Aceptación:*
- `POST /radar/descartes` acepta hasta cien ids y un motivo; responde con
  conteo y rechazados.
- Asignar en lote no crea dos oportunidades del mismo expediente (unicidad
  de `v61`); la segunda petición es idempotente.
- Un descarte por `competencia` de un expediente que luego gana una empresa
  vigilada aparece en H4.3 (test).
- `radar_triaje` gana `motivo` y `lote ∈ {1, 2-10, 11+}`.

*Adopción:* las dos propiedades nuevas de `radar_triaje`.

#### H3.7 Vistas compartidas y regla desde una vista — P2

**Para quién.** Quien ya construyó el filtro bueno. **Qué.** El menú de
vistas guardadas manda `visibility` y muestra «Vistas de la organización»;
«Crear regla desde esta vista» convierte los filtros en una regla (S4.4) con
vista previa (F5.5) y la vista guarda el `rule_id` para enlazarlos. **Hoy.**
Hecho 20. **Depende de.** S4.4 para los campos que hoy no existen en reglas.
**Esfuerzo / gate.** S · **[§6]** migración (`saved_filters.rule_id`),
pre-autorizada.

*Aceptación:*
- `saved-views.ts` manda `visibility` y `organization_id`; test de
  componente sobre el menú.
- Mapeo vista → regla con test de los campos sin equivalente (`q` libre
  → `keyword`; `rango` → sin equivalente, declarado en el diálogo).

*Adopción:* `vista_guardada` gana `compartida`; `regla_creada` gana
`origen=vista`.

#### H3.8 Bandeja de avisos — P1

**Para quién.** Quien perdió un aviso porque la campana solo enseña cinco.
**Qué.** Página «Avisos» en Resumen con el historial completo de
`user_notifications`, filtros por tipo y expediente, «marcar todo» y enlace
a las preferencias (C2.7); los recordatorios de plazo salen también por
email según preferencia; un digest cuyo SMTP falla no se marca enviado.
**Hoy.** Hecho 21. **Depende de.** Preferencias (C2.7). **Esfuerzo / gate.**
S · sin gate.

*Aceptación:*
- `GET /notifications?tipo=&expediente=&cursor=` paginado; la campana enlaza
  a la página.
- `deadline_reminders` publica por el outbox (S4.1) cuando exista; hasta
  entonces respeta C2.7 al encolar el digest.
- `mark_digests_sent` solo marca los enviados; los fallidos se reintentan
  como máximo tres veces y quedan en `ops_events` (test con SMTP simulado
  que falla).

*Adopción:* `vista=avisos` en `espacio_abierto`.

### H4 — Aprender del resultado

#### H4.1 Puntos por criterio: el debrief de la oferta — P0

**Para quién.** Quien quiere saber si perdió por precio o por técnica.
**Qué.** Al cerrar una oportunidad, tabla de puntuación por criterio (los de
`award_criteria`): puntos propios, puntos del ganador, precio del ganador y
número de licitadores; analítica «dónde perdemos» (precio frente a técnica)
junto a los motivos de F3.1 y en F4.2; la brecha calibra el simulador de
F2.2. **Hoy.** Hecho 22. **Depende de.** Motivos de pérdida (F3.1); F2.2.
**Esfuerzo / gate.** S · **[§6]** migración (`pursuit_scores`),
pre-autorizada.

*Aceptación:*
- Entrada manual validada contra `weight_pct` (puntos ≤ peso); sin criterios
  en la ficha, tabla libre con nombre de criterio.
- `GET /pursuits/metrics` gana `brecha_media_precio` y
  `brecha_media_tecnica`, solo con `n ≥ 5` y declarado.
- Test: tres cierres con brecha técnica → «perdemos en técnica».

*Adopción:* evento nuevo `debrief_guardado` con
`criterios ∈ {1-3, 4-6, 7+}`.

#### H4.2 Cuadro de ofertas de cada licitación (D45) — P0

**Para quién.** Todos: es la mitad del mercado que hoy no se ve. **Qué.**
Familia `bid_results` extraída de los documentos de adjudicación (informe de
valoración, acta, resolución): licitadores, precio ofertado, puntos por
criterio, exclusiones y bajas temerarias, con evidencia; tabla
`ofertas_licitadores`; se muestra en la ficha, en el perfil del competidor
(frecuencia de presentación y no solo victorias) y en las batallas de F3.2;
alimenta las bajas de referencia con ofertas perdedoras y retira el primer
bloqueador de `WinProbabilityGate`. **Hoy.** Hechos 2 y 23. **Depende de.**
D45, golden de fichas (C5.1), importe con semántica (C1.1). **Esfuerzo /
gate.** L · **[§6]** migración, pre-autorizada.

*Aceptación:*
- Spike escrito: en cincuenta expedientes adjudicados con documentos,
  cuántos traen informe con tabla de ofertas y en qué formato (texto o
  escaneado, este último a la espera de S8.3); se construye si al menos el
  40 % traen texto.
- Golden de treinta informes con la tabla esperada; precisión ≥ 0,9 en
  licitador y precio, ≥ 0,8 en puntos.
- Coste acotado por D45 y dentro de `LLM_BUDGET_*`; contador por expediente
  en `/ops`.
- Cada fila con `EvidenceRef`; sin evidencia no se persiste; nombres
  resueltos al maestro de empresas (`v35`) con su cola de revisión.
- `WinProbabilityGate.blockers` pierde el primero cuando hay al menos
  quinientas ofertas perdedoras con precio; sigue bloqueado por los otros
  dos.

*Adopción:* evento nuevo `cuadro_ofertas_abierto` con
`licitadores ∈ {1, 2-4, 5+}`.

#### H4.3 Retrospectiva de descartes — P2

**Para quién.** Quien quiere saber si tría bien. **Qué.** «Lo que
descartaste» en Mi Pipeline: descartes ya adjudicados con quién ganó, con
qué baja y si era una empresa vigilada; acierto del triaje por motivo (D43)
y sugerencia de ajustar reglas o ámbito (F6.1). **Hoy.** Hecho 19.
**Depende de.** H3.6; calidad del Radar (S3.2). **Esfuerzo / gate.** S · sin
gate.

*Aceptación:*
- Declara `n` y ventana; con menos de veinte descartes adjudicados muestra
  «sin datos suficientes» (ADR-014).
- Test: descarte por `competencia` ganado por una empresa vigilada → fila
  marcada.

*Adopción:* `vista=retrospectiva` en `espacio_abierto`.

## 4. Métricas de cierre del plan

Cada una con fecha, medida al cerrar la última entrega de §5 y sesenta días
después. Las de adopción salen del catálogo de `lib/analytics.ts`; las de
producto, de `make product-status` y de los tests.

| Métrica | Hoy (2026-09-06) | Objetivo |
|---|---|---|
| Organizaciones con NIF que resuelven «Mi empresa» (H1.1) | no existe | ≥ 80 % de las que tienen NIF |
| Bloqueadores de `WinProbabilityGate` (H4.2) | 3 | 2, con la cifra de ofertas perdedoras publicada en `/ops` |
| Expedientes adjudicados del ámbito de D45 con cuadro de ofertas (H4.2) | 0 | ≥ 40 % de los que traen informe con texto |
| Oportunidades perdidas con debrief (H4.1), a 90 días | no existe | ≥ 50 % |
| Descartes del Radar con motivo (H3.6) | 0 % | ≥ 70 % |
| p95 de la búsqueda en pliegos (H1.5) | no existe | < 800 ms, medido con fecha |
| Búsquedas con `ambito=pliegos` (H1.5), a 60 días | 0 | ≥ 20 % de `busqueda_realizada` |
| Oportunidades abiertas con alguna bandera de salud (H3.5), a 60 días | sin medir | ≤ 25 % |
| Oportunidades con hoja de costes antes de `submitted` (H2.1) | 0 | ≥ 60 % de las presentadas |
| Fallos de aislamiento en tests y `fuzz-api` con invitados (H3.2) | no aplica | 0 |
| Digests marcados enviados sin envío (H3.8) | todos los fallidos | 0 |
| Expedientes con `sistema_contratacion` informado (H1.3), si D40 aprueba | 0 | la cobertura que fije el spike, con fecha |

## 5. Orden de entrega

Cuatro entregas. La primera no depende de ningún otro plan y cabe en unos
diez días de agente; las demás esperan a las piezas que citan. Dentro de
cada entrega, un stream por rama.

1. **Sin dependencias externas.** H1.2, H1.5, H3.4, H3.5, H3.7, H3.8, H4.1
   (la tabla; la analítica por motivo espera a F3.1) y H2.8 en su parte de
   exportación (`pdf` en el desplegable). Cierra con `make check`,
   `make check-api-contract` y `make web-test`.
2. **Tras S2 y C6 de los otros planes.** H1.1 (S2.1, S2.2), H2.1 (C1.1),
   H2.2 (F2.3, C6.4), H2.4 (C6.1), H3.6 (F1.6; T1 cuando llegue), H4.3
   (H3.6, S3.2) y H1.6 (F1.2, S4.1).
3. **Tras los spikes y decisiones.** H1.3 (D40), H2.6 (D42), H4.2 (D45,
   C5.1), H2.3 (F2.5) y H2.5 (F5.1). Cada spike termina en un documento de
   `docs/plans/` con muestra, cifra y decisión antes de abrir la rama.
4. **Lo que toca a personas y a terceros.** H3.1 (D46), H3.2 (D44, S1.1),
   H3.3 (S4.4, F6.1), H2.7 (C6.3, S8.1) y H1.4 (D41, C1.2).

Dependencias entre ítems de este plan: H2.1 → H2.2 (coste de oferta) y
H2.8; H2.5 → H2.3 (desanclado); H3.6 → H4.3; H4.2 → H1.1 (tasa de éxito
pública). Ninguna otra.

## 6. Lo que NO se hace

- **Backup y restore drill.** Fuera por decisión del mantenedor.
- **Presentar la oferta.** La plataforma no firma ni presenta nada en
  PLACSP: prepara, contrasta y recuerda. El DEUC de H2.6 se descarga; lo
  presenta la persona.
- **Prosa de oferta generada por IA.** Sigue D33: la biblioteca de H2.7
  recupera y cita lo que la organización escribió; no redacta.
- **Probabilidad de ganar.** H4.2 retira un bloqueador de tres; los otros
  dos (validación temporal y calibración) siguen y la puerta sigue cerrada.
- **Cortes analíticos nuevos en Mercado.** H1.2 enriquece un endpoint que
  ya existe y se pinta donde ya se pintaba; no abre vistas.
- **Curriculum completo ni datos sensibles de empleados.** H3.1 guarda lo
  mínimo para adscribir y contrastar; los CV, si hacen falta, viajan como
  adjuntos de C6.3 bajo la misma política.
- **Portales ni fuentes nuevas de licitaciones.** H1.4 pide una excepción
  para un único dato abierto por entidad (D41); todo lo demás sigue en D16.
- **Traducción de pliegos en lenguas cooficiales.** El asistente ya responde
  en castellano sobre cualquier pliego; un producto de traducción es otra
  cosa.
- **Extracción de informes de valoración escaneados** hasta que exista el
  OCR de S8.3; H4.2 lo mide y lo deja fuera del objetivo.
- **App nativa y web push.** Como en los planes anteriores.
