---
tags: [plan, producto, funcionalidades, multi-agente]
---

# Plan de funcionalidades 2026-09 — lo que el usuario va a poder hacer

Tercer plan de la serie de septiembre. Los dos anteriores miran la
arquitectura: [v2](2026-09-plan-arquitectura-v2.md) cierra los bucles de
operación, identidad, eventos y etiquetas, y el
[complementario](2026-09-plan-arquitectura-v2-complementario.md) añade
maestros, cuentas, plataforma y contrato. Este mira **la aplicación desde la
silla del usuario**: qué puede hacer hoy en cada paso de su trabajo, qué no
puede, y qué funcionalidad lo resuelve. Está organizado por recorrido, no
por capa: descubrir, calificar, competir, ejecutar, vigilar, configurar.

Redactado el 2026-09-05 sobre el mismo árbol (rama
`claude/app-architecture-review-d3vcog`, base `master` = `17169ce`). Cada
funcionalidad dice qué hay hoy, con referencia, y de qué ítem de los otros dos
planes depende cuando depende de alguno. No repite lo que allí está
planificado: cuando una funcionalidad de aquí necesita una pieza de allí, la
cita y no la redefine.

**Estado: PROPUESTO el 2026-09-05.** Nada de este documento está implementado.
Mismo contrato de ejecución que sus hermanos: un stream por rama y por
agente, este documento como única fuente de alcance y criterios, y los gates
de AGENTS.md §6 marcados **[§6]** salvo lo que D39 pre-autoriza.

## 0. Alcance y método

**Qué cubre.** Treinta y ocho funcionalidades en seis recorridos (F1–F6),
cada una con: para quién es, qué hace, qué hay hoy (verificado), de qué
depende, esfuerzo, gate, criterios de aceptación observables por el usuario y
medibles por comando o test, y **su métrica de adopción** en el catálogo de
telemetría de `web/src/lib/analytics.ts`, con la misma regla que ese fichero
impone: dimensiones categóricas de cardinalidad baja, nunca identificadores
ni texto del usuario.

**Qué queda fuera.** El backup y el restore drill, por decisión del
mantenedor; todo lo que v2 y el complementario ya planifican; y lo listado en
§6. Este plan no añade cortes analíticos a Mercado ni espacios de consola
salvo los dos que §3 justifica con una función nueva (Cuentas y Dirección),
que absorben vistas existentes y no las duplican.

**Prioridad.** Misma escala que `docs/UX_AUDIT.md`: **P0** cierra una
promesa del producto («dónde pujar, a qué precio, contra quién»), **P1**
quita un daño diario, **P2** quita fricción acumulada. El orden de entrega
está en §5.

**Convenciones.** Esfuerzo **S** / **M** / **L** como en v2. Las cifras
llevan fecha y se vuelven a medir. Un criterio de aceptación que no se pueda
comprobar no entra.

### Por qué estas y no otras

Las funcionalidades salen de cruzar el recorrido del usuario con lo que el
código ya sabe y no enseña. Hay tres patrones repetidos:

1. **Dato que existe y no llega al usuario.** Procedimiento y tramitación
   desde `v85`, lead-time del órgano, sugerencia de socios, cita con offsets:
   están calculados o persistidos y ninguna pantalla los ofrece donde se
   decide.
2. **Decisión que el producto captura y no explota.** Motivo de pérdida,
   precio ofertado, score al abrir: se guardan y no se convierten en
   aprendizaje ni en cuadro de mando.
3. **Pregunta del usuario sin respuesta.** «¿Cuántos puntos me da esta baja?»,
   «¿qué documentos tengo que presentar?», «¿cuándo se adjudicará?», «¿qué
   cambió desde ayer en lo que sigo?». Ninguna la responde hoy una pantalla.

## 1. Hechos verificados (2026-09-05)

1. **Filtros del listado.** `GET /licitaciones` acepta `ccaa`, `tecnologia`,
   `estado`, `fecha_desde`, `fecha_hasta`, `cierre_desde`, `cierre_hasta`,
   `q`, `solo_abiertas`, `sort`, `tecnologia_predicha` y `min_proba_tech`
   (`api/routes/licitaciones.py`). No acepta importe, CPV, órgano, provincia,
   procedimiento ni tipo de contrato, aunque `LicitacionesFilters` del
   repositorio de agregados ya modela `cpv` e `importe_min`
   (`db/repositories/aggregates.py:107-119`).
2. **Paleta ⌘K.** Navega entre espacios, salta a un expediente por id y manda
   texto libre a Detalle; no busca empresas, órganos ni oportunidades
   (`web/src/components/command-palette.tsx`, sin coincidencias).
3. **Score.** Desglose numérico y `risk_flags` con `sin_importe`,
   `sin_plazo`, `sin_historico_competencia` y `fuera_de_rango`
   (`services/analytics/scoring.py:407-446`); sin señal de anulación ni
   desierto (`ANUL` solo aparece en el embudo, `services/analytics/overview.py:313`).
4. **Procedimiento y tramitación.** Columnas desde `v85`; la consola no las
   pinta ni tiene mapa de etiquetas: en `web/src` solo aparecen en la ficha
   pública, en los ejemplos del copiloto y en el Investigador.
5. **Hitos del procedimiento.** El parser solo extrae plazos de presentación
   (`scraper/codice_parser.py:246-273`); no hay eventos de apertura de sobres
   ni fecha prevista de adjudicación, y los fixtures CODICE no contienen
   `OpenTenderEvent` (0 coincidencias en `tests/fixtures/`).
6. **Ficha del pliego.** Familias actuales en `shared/tender_facts.py:106-123`:
   lotes, criterios, solvencias, garantías, penalidades, ANS, subcontratación,
   equipo, certificaciones, prórrogas, plazos críticos y tecnologías. Sin
   fórmula de valoración del precio, documentos exigidos, tarifas por perfil
   ni desglose del presupuesto (sin coincidencias de `formula`).
7. **Evidencias.** La ficha muestra la cita
   (`web/src/components/pursuits/tender-fact-sheet.tsx`); no hay visor de
   página, aunque `documento_pages` guarda texto y offsets por página.
8. **PDF de oportunidad.** No existe (sin coincidencias de `pdf` en
   `oportunidades/` ni de `pursuit` en `services/exports.py`).
9. **Métricas de oportunidades.** `PursuitMetrics` trae conteos por estado,
   `win_rate`, `awarded_amount_eur` y mediana de tiempo de decisión
   (`shared/dto.py:897-906`); sin valor ponderado ni previsión.
10. **Motivo de pérdida.** `outcome_reason` es texto libre
    (`shared/dto.py:729`); no hay código ni analítica de motivos.
11. **Socios.** `services/partners.py` expone `suggest_partners`,
    `segment_winners` y `company_profile` sin ningún consumidor; solo
    `build_partnership_graph` se usa (`services/analytics/utes.py:22`).
12. **Lead-time del órgano.** Existe (`services/analytics/organo_detail.py:64`,
    `:123`) y se pinta en Mercado → Órganos y en la tira de contexto del
    Resumen; no se usa para prever cuándo se adjudicará una oportunidad
    (`PursuitSummary` no tiene ese campo).
13. **Alertas de competidor.** Detectan adjudicaciones nuevas y vencimientos
    de las empresas vigiladas (`scheduler/competitor_alerts.py`); no cruzan
    con las oportunidades abiertas ni con órganos seguidos.
14. **Documentos nuevos.** No existe ningún evento de «documento publicado»
    (sin coincidencias); la identidad por hash de `v88` permitiría emitirlo
    sin duplicados por rotación de token.
15. **Ámbito de la organización.** `OrganizationSettings` solo tiene
    `tecnologias` (`shared/dto.py:644-667`); CPVs, importe y keywords viven en
    el perfil personal (`api/routes/me.py:339-351`). No hay ámbito de mercado
    de organización.
16. **Superficie pública.** Hubs por CCAA y CPV (`api/routes/publico.py`);
    ninguno por órgano. La política de la superficie pública excluye todo
    campo derivado del pipeline, incluida la tecnología
    (`db/repositories/publico.py`), así que un hub por tecnología no cabe sin
    cambiarla.
17. **Telemetría.** Catálogo de catorce eventos en `web/src/lib/analytics.ts`:
    `sesion_iniciada`, `espacio_abierto`, `radar_triaje`,
    `licitacion_seguida`, `pursuit_creado`, `pursuit_estado_cambiado`,
    `perfil_configurado`, `onboarding_ocultado`, `regla_creada`,
    `asistente_usado`, `asistente_feedback`, `export_lanzado`,
    `busqueda_realizada` y `vista_guardada`.
18. **Descartes del Radar.** Persisten en `radar_dismissals` (`v76`) hasta
    deshacer; no hay «silenciar durante N días» ni «recordar en».

## 2. Decisiones del mantenedor (D32–D39)

Continúa la numeración de los planes anteriores.

| Id | Decisión | Desbloquea |
|---|---|---|
| D32 | **Hitos del procedimiento.** Antes de construir, un spike de una semana mide en un mes de entradas ATOM si CODICE publica eventos de apertura y en qué proporción. Se construye solo si la cobertura supera el 30 %; si no, la fecha prevista de adjudicación (F4.4) se estima sola. | F2.1 |
| D33 | **Guion de la oferta técnica.** ¿Solo esquema de puntos con citas al pliego, o también prosa? Propuesta: solo esquema; la prosa la escribe el equipo. Un producto que vende confianza en el dato no puede ofrecer párrafos inventados. | F2.6 |
| D34 | **Probabilidad por etapa.** Valores por defecto para el valor ponderado (`identified` 10 %, `qualifying` 20 %, `go_no_go` 30 %, `preparing` 50 %, `submitted` 60 %) y edición por owner/admin. Propuesta: sí, con la advertencia de que son supuestos hasta que F3.1 acumule cierres. | F4.1 |
| D35 | **CRM.** ¿Plantilla genérica de webhook más CSV con mapeo, o conector nativo desde el principio? Propuesta: plantilla y CSV; el conector nativo cuando una organización lo pida por escrito y diga cuál. | F6.3 |
| D36 | **Boletín público.** ¿Un digest público por CCAA y CPV como captación? Propuesta: no hasta que exista dominio propio (v2 S1.3) y política de privacidad para suscriptores; se reevalúa entonces. | F6.6 |
| D37 | **Motivos de pérdida.** Lista cerrada: `precio`, `tecnica`, `solvencia`, `plazo`, `desierto_o_anulado`, `no_presentada`, `otro` con texto. Propuesta: cerrada, porque una lista abierta no se puede agregar. | F3.1 |
| D38 | **Etiquetas.** Libres por organización, hasta treinta, con color; aplicables a favoritos, oportunidades y cuentas. Propuesta: sí. | F1.6 |
| D39 | **Gates §6 pre-autorizados para este plan.** Migraciones de F1.4, F1.5, F1.6, F2.1, F3.1, F4.1, F4.3, F5.6, F6.1 y F6.4 en los términos de cada ítem; `.env.example` para las variables de F2.6 y F6.3. Ninguna edición de workflows ni dependencia nueva: las exportaciones usan `reportlab`, que ya está. | todos |

Mientras D32–D38 no estén cerradas, los ítems que las citan no se empiezan.

---

## 3. Funcionalidades por recorrido

Cada ítem: **Para quién** · **Qué** · **Hoy** · **Depende de** · **Esfuerzo /
gate** · **Aceptación** · **Adopción** (evento o propiedad del catálogo).

### F1 — Descubrir: Radar, listado y búsqueda

#### F1.1 Filtros que faltan en el listado y la barra de ámbito — P0

**Para quién.** Cualquiera que busque. **Qué.** Importe mínimo y máximo, CPV
por prefijo, órgano (con autocompletado), provincia, procedimiento,
tramitación, tipo de contrato y plazo restante en días, en `GET /licitaciones`,
en `/licitaciones/cursor` y en la barra de ámbito; los exports los respetan.
**Hoy.** Hecho 1. **Depende de.** Nada; F1.7 aporta las etiquetas de
procedimiento. **Esfuerzo / gate.** M · sin gate.

*Aceptación:*
- Los filtros viajan en la URL (`nuqs`) y el contrato por página de
  `lib/navigation.ts` los declara donde aplican; un filtro inerte no se
  muestra (regla de la barra de ámbito).
- `GET /meta/filters` devuelve las opciones de procedimiento, tramitación y
  tipo de contrato con etiqueta.
- Test de paridad: el mismo filtro devuelve el mismo `COUNT(*)` en listado,
  cursor, overview y export (extiende S4.1 del plan de septiembre).
- El plazo restante se calcula en SQL sobre `fecha_limite` y excluye estados
  terminales.

*Adopción:* `busqueda_realizada` gana la propiedad `filtros` con el número de
filtros activos en tramos (`0`, `1-2`, `3+`).

#### F1.2 Búsqueda global unificada en ⌘K — P1

**Para quién.** Todos. **Qué.** La paleta busca expedientes (id y título),
empresas (nombre y NIF exacto), órganos y oportunidades de la organización,
con etiqueta de tipo y atajo por tipo. **Hoy.** Hecho 2. **Depende de.** El
maestro de órganos del complementario (C1.2) para que el resultado «órgano»
sea una entidad; hasta entonces busca sobre el nombre normalizado.
**Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- `GET /search/global?q=` tipado, con ámbito de organización para
  oportunidades y `limit` por tipo.
- Un NIF exacto abre el perfil de empresa sin pasar por la lista.
- Sin resultados, la paleta dice qué buscó y ofrece «buscar en Detalle».
- p95 por debajo de 300 ms sobre el fixture de CI.

*Adopción:* `busqueda_realizada` con `origen=paleta` y `tipo_resultado`.

#### F1.3 Explicación del score en lenguaje claro — P0

**Para quién.** Quien tría en el Radar. **Qué.** Tres frases por tarjeta,
generadas por plantillas en backend a partir del desglose y de los
`risk_flags`, sin LLM: «Puntúa 82: importe en el tramo alto de tu rango, dos
ofertas de media en este CPV, baja esperada del 12 %». **Hoy.** Desglose
numérico en un popover. **Depende de.** Nada. **Esfuerzo / gate.** S · sin
gate.

*Aceptación:*
- `ScoredOpportunity.explicacion: list[str]` (aditivo), una frase por
  dimensión con dato, y una por cada `risk_flag`.
- Ninguna frase contiene una cifra que no esté en `desglose` o en las
  señales (ADR-014); test por combinación de dimensión y origen
  (`margen_origen`, `afinidad_origen`).
- Una dimensión neutral por falta de datos lo dice («sin importe publicado:
  puntúa neutral»), no lo disimula.

*Adopción:* `radar_triaje` gana `explicacion_abierta`.

#### F1.4 Riesgo de desierto o anulación como señal — P1

**Para quién.** Quien decide dónde invertir horas de oferta. **Qué.** Tasa
histórica de expedientes anulados o desiertos del órgano y del CPV a cuatro
dígitos en 24 meses; entra en `risk_flags` como `organo_anula_frecuente` con
penalización configurable y aparece en la explicación de F1.3. **Hoy.** Hecho
3. **Depende de.** Nada; mejora con el maestro de órganos (C1.2).
**Esfuerzo / gate.** S · **[§6]** migración de la tabla de tasas
precalculadas, pre-autorizada.

*Aceptación:*
- Cálculo en SQL en el precómputo de agregados, con `n` mínimo de diez
  expedientes; por debajo, sin señal y declarado.
- El peso de la penalización vive en `SCORING_WEIGHTS` y el perfil puede
  ponerlo a cero.
- Test con fixture de un órgano con el 40 % de anulaciones.

*Adopción:* propiedad `flag=organo_anula_frecuente` en `radar_triaje`.

#### F1.5 Cuentas objetivo: seguir un órgano — P0

**Para quién.** Comercial que trabaja cuentas, no expedientes. **Qué.**
Marcar un órgano como cuenta objetivo de la organización y abrir su vista:
contratos vigentes en mis tecnologías con incumbente y fecha de fin,
publicaciones recientes, lead-time medio (ya calculado), estacionalidad
cuando exista (v2 T5), oportunidades del equipo con ese órgano y siguiente
acción. Espacio «Cuentas» en el grupo de trabajo, que absorbe la vista
Órganos de Mercado como `?vista=mercado` (consolidar no elimina). **Hoy.**
Órganos es un corte analítico sin acción; no se puede seguir un órgano.
**Depende de.** Seguimiento unificado de v2 (T1) para el «seguir»; hasta
entonces, tabla propia `cuentas_objetivo` que T1 absorbe. **Esfuerzo / gate.**
L · **[§6]** migración, pre-autorizada.

*Aceptación:*
- `POST /cuentas` con el órgano (nombre normalizado hoy, `organo_id` cuando
  llegue C1.2) y ámbito de organización; un `viewer` no puede crear.
- La vista declara universo y ventana en cada bloque (ADR-014) y no suma
  fuentes regionales como censo.
- Seguir un órgano genera aviso de publicación nueva y de vencimiento a seis
  meses (por el outbox de v2 S4.1; hasta entonces, por el job de reglas).
- `console-spaces.ts` incorpora el espacio con su redirect y los tests de
  títulos lo derivan.

*Adopción:* evento nuevo `organo_seguido` y propiedad `espacio=cuentas` en
`espacio_abierto`.

#### F1.6 Etiquetas de organización (D38) — P2

**Para quién.** Equipos que organizan por trimestre, línea de negocio o
prioridad. **Qué.** Etiquetas libres por organización sobre favoritos,
oportunidades y cuentas; filtro por etiqueta en Radar, Detalle y
Oportunidades. **Hoy.** No existen (sin coincidencias de `etiqueta` ni `tag`
en persistencia). **Depende de.** Nada. **Esfuerzo / gate.** S · **[§6]**
migración, pre-autorizada.

*Aceptación:*
- Tablas `etiquetas` y `etiquetas_aplicadas` con ámbito de organización;
  límite de treinta etiquetas por organización.
- El export CSV incluye la columna de etiquetas; el export GDPR incluye las
  aplicadas por el usuario.
- Test de aislamiento: una etiqueta de otra organización no aparece ni filtra.

*Adopción:* evento nuevo `etiqueta_aplicada` con `objeto ∈ {favorito,
oportunidad, cuenta}`.

#### F1.7 Procedimiento y tramitación legibles — P1

**Para quién.** Todos; sobre todo quien no vive en la Ley 9/2017. **Qué.**
La consola muestra procedimiento (abierto, simplificado, negociado, etc.) y
tramitación (ordinaria, urgente, emergencia) con etiqueta legible y tooltip,
en el inspector, la tabla de Detalle, el Radar y los filtros de F1.1. **Hoy.**
Hecho 4. **Depende de.** Nada. **Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- Mapa versionado código CODICE → etiqueta en `shared/procedimientos.py`,
  expuesto por `GET /meta/filters`; el frontend no copia la lista (invariante
  3 de `web/AGENTS.md`).
- Un código desconocido se muestra tal cual con aviso «código no
  catalogado» y cuenta en `/analytics/quality`.
- Test de que cada código presente en el corpus de CI tiene etiqueta.

*Adopción:* ninguna propia; F1.1 la cubre.

#### F1.8 Glosario contextual — P2

**Para quién.** Usuarios nuevos. **Qué.** Un `?` junto a estados, procedimientos,
«baja», «UTE», «PYME», «valor estimado» y «lote» con una definición corta y
enlace a `/metodologia`. **Hoy.** `lib/estados.ts` da etiquetas, no
explicaciones. **Depende de.** Nada. **Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- Un solo diccionario en `web/src/lib/glosario.ts`; test de que cada estado
  de `estados.ts` y cada código de F1.7 tiene entrada.
- Accesible por teclado y anunciado por lector (patrón de `Tooltip`, no
  `title=`).

*Adopción:* propiedad `glosario_abierto` en `espacio_abierto`, sin el término.

### F2 — Calificar: la oportunidad y su pliego

#### F2.1 Hitos del procedimiento (D32) — P1

**Para quién.** Quien prepara la oferta. **Qué.** Apertura de sobres, fin del
plazo de consultas, visita obligatoria y fecha estimada de adjudicación
(F4.4), en la ficha, en la agenda y en el ICS. **Hoy.** Hecho 5.
**Depende de.** D32 (spike). **Esfuerzo / gate.** M · **[§6]** migración de
`licitacion_hitos`, pre-autorizada.

*Aceptación:*
- El spike deja un documento en `docs/plans/` con la muestra, los elementos
  encontrados y la cobertura medida.
- Si se construye: parser con test por fixture, tabla `licitacion_hitos`
  (tipo, fecha, fuente), recordatorios en las ventanas de
  `services/deadline_reminders.py`, y la agenda distingue «hito publicado» de
  «fecha estimada».

*Adopción:* propiedad `hito_visto` en `espacio_abierto`.

#### F2.2 Simulador de puntuación de la oferta — P0

**Para quién.** Quien fija el precio. **Qué.** Con los criterios y pesos de
la ficha, el peso del precio (`v85`), la fórmula de valoración del precio
(familia nueva) y los escenarios de baja existentes: «con una baja del 12 %
obtienes 38 de 45 puntos de precio; para ganar a un rival que baje el 18 %
necesitas 7 puntos más en juicio de valor». **Hoy.** Escenarios de precio y
criterios existen por separado; nadie los une, y la fórmula no se extrae
(hecho 6). **Depende de.** Ficha (v2 S3 no; ya existe). **Esfuerzo / gate.**
M · sin gate.

*Aceptación:*
- Familia `price_formula` en `TenderFactSheet` (tipo ∈ {proporcional_inversa,
  lineal_por_tramos, con_umbral_temeridad, otra}, parámetros y evidencia);
  entra en el golden de fichas del complementario (C5.1).
- `GET /licitaciones/{id}/simulador?baja=` devuelve puntos de precio por
  fórmula y el hueco de juicio de valor frente a bajas de referencia
  (`bajas/referencia` y p10/p50/p90 de `prediccion-baja`).
- Sin fórmula extraída, el simulador dice «fórmula no encontrada en el
  pliego» y no calcula; sin peso del precio, igual.
- Test contra diez pliegos golden con puntuación calculada a mano.

*Adopción:* evento nuevo `simulador_usado` con `formula_tipo`.

#### F2.3 Kit de presentación: documentos exigidos — P0

**Para quién.** Quien monta la oferta administrativa. **Qué.** Lista de
documentos que exige el pliego (DEUC, acreditación de solvencia, garantía
provisional, compromiso de UTE, declaraciones responsables, muestras),
extraída como familia `required_documents` con evidencia, convertida en
checklist con estado y responsable. **Hoy.** Hecho 6; el checklist de
capacidad de v2 S2.3 dice si cumplimos, no qué hay que entregar.
**Depende de.** Tareas del complementario (C6.1) para el responsable; sin
ellas, checklist sin responsable. **Esfuerzo / gate.** M · sin gate.

*Aceptación:*
- Familia con evidencia y `scope ∈ {sobre_a, sobre_b, sobre_c, otro}`; golden
  compartido con C5.1.
- La pestaña Decisión muestra el kit con casillas persistidas en
  `pursuit_events` (`kit_item_marcado`).
- Sin documentos extraídos, el kit está vacío y lo dice; nunca propone una
  lista genérica como si fuera del pliego.

*Adopción:* evento nuevo `kit_abierto` con `items` en tramos.

#### F2.4 Tarifas por perfil y desglose del presupuesto — P1

**Para quién.** Quien calcula el margen. **Qué.** Familias `rate_cards`
(perfil, tarifa máxima por hora, horas estimadas) y `budget_breakdown`
(costes directos, indirectos, salariales), con evidencia; los escenarios de
precio muestran el margen implícito cuando hay tarifas. **Hoy.** Hecho 6.
**Depende de.** Nada. **Esfuerzo / gate.** M · sin gate.

*Aceptación:*
- Golden con al menos diez pliegos de servicios TI con tarifas.
- `escenarios-precio` gana `margen_implicito` solo cuando hay tarifas y
  horas; declara la fuente.
- Ninguna tarifa sin `EvidenceRef`.

*Adopción:* propiedad `con_tarifas` en `simulador_usado`.

#### F2.5 Visor de página con la cita resaltada — P1

**Para quién.** Quien verifica una evidencia. **Qué.** Al pulsar una cita,
se abre la página de `documento_pages` con el fragmento resaltado por
offsets, navegación entre páginas y enlace al documento original. Sin
binario. **Hoy.** Hecho 7. **Depende de.** Nada; el binario (v2 S8.1) añade
después el PDF real. **Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- `GET /licitaciones/{id}/documentos/{documento_id}/paginas/{n}` tipado.
- Offsets inválidos → página completa sin resaltado y aviso; test.
- E2E: desde la ficha a la página resaltada en dos clics.

*Adopción:* propiedad `evidencia_abierta` en `espacio_abierto`.

#### F2.6 Guion de la oferta técnica por criterio (D33) — P1

**Para quién.** Quien redacta. **Qué.** Para cada criterio de adjudicación,
un esquema de puntos a cubrir con citas al pliego y a los requisitos
técnicos; exportable en Markdown y PDF. Solo esquema. **Hoy.** El asistente
responde preguntas; no estructura la respuesta por criterio. **Depende de.**
Presupuesto LLM por organización (C2.9). **Esfuerzo / gate.** M · **[§6]**
`.env.example` para el tope por guion, pre-autorizado.

*Aceptación:*
- Cada punto lleva al menos una cita válida (existe en `documento_pages`);
  un punto sin cita se marca «sin base en el pliego».
- Se cachea por firma de ficha y documentos (misma regla que el resumen).
- Un test de contrato impide que la respuesta contenga párrafos de más de
  dos frases (esquema, no prosa).

*Adopción:* evento nuevo `guion_generado` con `criterios` en tramos.

#### F2.7 Ficha de oportunidad en PDF — P1

**Para quién.** Quien lleva la decisión a dirección. **Qué.** Un one-pager:
resumen, criterios y pesos, competencia esperada, escenarios de precio,
checklist, decisión, responsable, próxima acción. **Hoy.** Hecho 8.
**Depende de.** Nada (`reportlab` ya está). **Esfuerzo / gate.** S · sin
gate.

*Aceptación:*
- `GET /pursuits/{id}/ficha.pdf` con ámbito de organización.
- El PDF declara fecha del dato y universo de cada bloque; un bloque sin
  datos se omite con nota, no se rellena.
- Test de que no incluye datos de otra organización ni PII de terceros.

*Adopción:* `export_lanzado` con `formato=pdf_oportunidad`.

#### F2.8 Comparar expedientes — P2

**Para quién.** Quien elige entre dos. **Qué.** Tabla determinística de las
familias de la ficha para hasta tres expedientes (sin LLM), y `/ask` acepta
hasta tres `id_externo` para preguntas cruzadas. **Hoy.** El comparador de
Detalle compara metadatos del anuncio, no fichas. **Depende de.** Nada.
**Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- `POST /licitaciones/comparar` tipado; familias vacías se muestran vacías.
- `/ask` con varios expedientes limita el contexto por expediente y lo
  declara en el evento `degraded` si trunca.

*Adopción:* propiedad `n_expedientes` en `asistente_usado`.

### F3 — Competir

#### F3.1 Motivos de pérdida codificados y analítica win/loss (D37) — P0

**Para quién.** Dirección y quien fija precio. **Qué.** Al cerrar `lost`, un
motivo codificado obligatorio más texto; analítica por tecnología, órgano,
procedimiento y competidor: «perdemos por precio en el 60 % de los casos en
CPV 72». **Hoy.** Hecho 10. **Depende de.** Nada. **Esfuerzo / gate.** S ·
**[§6]** migración, pre-autorizada.

*Aceptación:*
- `outcome_reason_code` con la lista de D37; `lost` sin código → 422.
- `GET /pursuits/metrics` gana `perdidas_por_motivo` con `n`; se pinta solo
  con al menos cinco cierres por corte.
- Backfill: los cierres existentes quedan en `sin_codificar` y la UI lo
  ofrece para completar.

*Adopción:* propiedad `motivo` en `pursuit_estado_cambiado` (categórica).

#### F3.2 Batallas directas por competidor — P1

**Para quién.** Quien conoce a sus rivales. **Qué.** Por competidor:
expedientes en los que concurrimos ambos (oportunidades presentadas y
adjudicaciones observadas), quién ganó, con qué baja, y nuestra baja
ofertada. **Hoy.** El perfil de empresa no sabe qué presentamos nosotros.
**Depende de.** NIF de la organización (v2 S2.1) para detectar «ellos
ganaron»; sin él, solo «nosotros perdimos». **Esfuerzo / gate.** M · sin
gate.

*Aceptación:*
- Vista en Competencia → Competidores, pestaña «Contra mí», con `n` y ventana.
- Solo oportunidades con `offer_price_eur`; sin precio, la fila lo dice.
- Test de aislamiento: no mezcla oportunidades de otra organización.

*Adopción:* propiedad `vista=contra_mi` en `espacio_abierto`.

#### F3.3 Socios de UTE sugeridos — P1

**Para quién.** Quien no llega solo a la solvencia. **Qué.**
`GET /competitive/partners?cpv=&ccaa=` sirve `suggest_partners` y
`segment_winners`; la oportunidad muestra «empresas que complementan tu
capacidad en este CPV», con el motivo (co-adjudicaciones, complementariedad de
CPV, tamaño). **Hoy.** Hecho 11. **Depende de.** Perfil de capacidad (v2
S2.2) para «complementan»; sin él, sugerencia por co-adjudicación.
**Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- Endpoint tipado con `LIMIT` (regla del escáner AST) y `n`.
- Cada sugerencia explica por qué; sin datos suficientes, lista vacía
  declarada.
- La sugerencia nunca incluye a la propia organización ni a competidores
  marcados como excluidos.

*Adopción:* evento nuevo `partners_consultado`.

#### F3.4 Alertas de competidor en mi segmento — P1

**Para quién.** Quien vigila. **Qué.** Ampliar las alertas de competidor:
«competidor vigilado gana en un CPV u órgano donde tengo oportunidades
abiertas o cuentas objetivo». **Hoy.** Hecho 13. **Depende de.** Outbox (v2
S4.1); cuentas (F1.5). **Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- Evento `competidor.adjudicacion_en_mi_segmento` en el catálogo de v2 S4.1.
- Test: adjudicación del competidor en un órgano seguido → alerta; en otro
  → nada.

*Adopción:* propiedad `tipo` en la lectura de alertas (sin evento nuevo).

#### F3.5 Perfil de competidor por procedimiento y tamaño — P2

**Para quién.** Quien estudia a un rival. **Qué.** Bajas y adjudicaciones
por tipo de procedimiento (`v85`) y por tramo de importe en el perfil de
empresa. **Hoy.** Cortes por CPV, CCAA y año. **Depende de.** F1.7.
**Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- Dos cortes nuevos con `n` por celda; sin `n` mínimo, celda vacía.

*Adopción:* ninguna propia.

### F4 — Ejecutar: pipeline y dirección

#### F4.1 Valor ponderado del pipeline y previsión (D34) — P0

**Para quién.** Dirección. **Qué.** `pipeline_value_eur` = suma de importe
por probabilidad de etapa, y previsión por trimestre a partir de la fecha
límite o de la fecha prevista de adjudicación (F4.4). **Hoy.** Hecho 9.
**Depende de.** Nada. **Esfuerzo / gate.** S · **[§6]** migración de la
configuración por organización, pre-autorizada.

*Aceptación:*
- `OrganizationSettings.probabilidades_etapa` con los defaults de D34;
  owner/admin editan.
- `PursuitMetrics` gana `pipeline_value_eur` y `prevision_trimestral`
  (aditivo), cada uno con los supuestos declarados.
- Test con fixture de ocho oportunidades y valores calculados a mano.

*Adopción:* propiedad `vista=embudo` ya existe en `espacio_abierto`; sin
evento nuevo.

#### F4.2 Cuadro de mando de dirección — P1

**Para quién.** Owner y admin. **Qué.** Espacio «Dirección» (grupo
organización, `visibility` por rol) que absorbe Mi Pipeline → Embudo como
vista: valor ponderado, win rate por tecnología y órgano, tiempo de ciclo,
motivos de pérdida (F3.1), precisión del Radar (v2 S3.2), actividad del
equipo. **Hoy.** Embudo con tres barras y cuatro cifras (128 líneas).
**Depende de.** F3.1, F4.1, v2 S3.2. **Esfuerzo / gate.** M · sin gate.

*Aceptación:*
- Cada tarjeta declara universo, ventana y `n` (ADR-014); ninguna pinta con
  `n` menor que el mínimo de su métrica.
- Solo owner/admin; un `member` recibe 403 en el endpoint, no solo un rail
  sin enlace.
- Las mismas consultas alimentan el informe semanal de v2 T6.

*Adopción:* propiedad `espacio=direccion` en `espacio_abierto`.

#### F4.3 Cartera de contratos en ejecución — P0

**Para quién.** El incumbente que quiere seguir siéndolo. **Qué.** Las
oportunidades ganadas pasan a «Cartera»: fecha de fin efectiva (ya calculada
por renovaciones), prórrogas y modificaciones (eventos de contrato), ventana
de relicitación esperada, y «preparar renovación», que crea una oportunidad
precargada con el expediente predecesor. **Hoy.** `won` es un estado
terminal sin vida posterior. **Depende de.** Outbox (v2 S4.1) para las
alertas; predecesor (C1.3) para enlazar la relicitación cuando se publique.
**Esfuerzo / gate.** M · **[§6]** migración de `contratos_cartera`,
pre-autorizada.

*Aceptación:*
- Vista Mi Pipeline → Cartera con filtros por tecnología y órgano.
- Alertas a seis, tres y un mes del fin efectivo, con opt-out.
- «Preparar renovación» crea la oportunidad en `identified` con nota que
  enlaza el contrato; idempotente.
- Test: una prórroga registrada por `contract_events` mueve la fecha de fin
  en la cartera.

*Adopción:* evento nuevo `cartera_abierta` y propiedad
`origen=renovacion` en `pursuit_creado`.

#### F4.4 Fecha prevista de adjudicación — P1

**Para quién.** Quien planifica recursos. **Qué.** `expected_award_date`
en cada oportunidad: fecha límite más la mediana del lead-time del órgano, con
rango p25–p75 y `n`; la agenda y F4.1 la usan. **Hoy.** Hecho 12.
**Depende de.** Nada; F2.1 la sustituye por el hito publicado cuando exista.
**Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- Nulo si el órgano tiene menos de cinco adjudicaciones en 24 meses; la UI
  muestra «sin estimación».
- Campo aditivo en `PursuitSummary` con `metodo ∈ {hito, estimacion}`.
- Test con fixture de órgano con lead-time conocido.

*Adopción:* ninguna propia.

#### F4.5 Actividad de la organización — P2

**Para quién.** Owner y admin. **Qué.** Feed de lo que hizo el equipo (abrió,
decidió, presentó, cerró, comentó, invitó) en Equipo → Actividad, filtrable
por persona y tipo. **Hoy.** El historial existe por oportunidad, no por
organización. **Depende de.** Outbox (v2 S4.1). **Esfuerzo / gate.** S · sin
gate.

*Aceptación:*
- Solo eventos de la organización; sin PII de terceros; paginado por cursor.
- Un `member` ve el feed sin los eventos de administración (invitaciones,
  roles).

*Adopción:* propiedad `vista=actividad` en `espacio_abierto`.

#### F4.6 Plantillas de tareas por etapa — P2

**Para quién.** Equipos con método. **Qué.** Al pasar una oportunidad a
`preparing`, se crean las tareas de la plantilla de la organización
(revisión legal, solvencia, precio, entrega); owner/admin la editan.
**Hoy.** Una sola `next_action`. **Depende de.** Tareas (C6.1).
**Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- Plantilla por organización con hasta veinte tareas y plazo relativo a la
  fecha límite.
- La transición crea las tareas una sola vez (idempotente por
  `pursuit_events`).

*Adopción:* propiedad `origen=plantilla` en la creación de tareas.

### F5 — Vigilar: alertas y novedades

#### F5.1 Aviso de documentos nuevos en expedientes seguidos — P0

**Para quién.** Todos los que siguen algo. **Qué.** Cuando `documentos`
incorpora un adjunto nuevo de un expediente seguido o con oportunidad
(pliego publicado tras el anuncio, rectificación, respuestas a consultas),
aviso con el tipo de documento y enlace. **Hoy.** Hecho 14. **Depende de.**
Outbox (v2 S4.1). **Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- Evento `licitacion.documento_nuevo` con `tipo`; la identidad por hash de
  `v88` evita repetir por rotación de token (test).
- La ficha marca «nuevo» durante siete días.

*Adopción:* propiedad `tipo=documento_nuevo` en la lectura de alertas.

#### F5.2 Recursos y resoluciones sobre expedientes seguidos — P1

**Para quién.** Quien tiene una oferta en juego. **Qué.** Una resolución del
TACRC vinculada a un expediente seguido o con oportunidad genera aviso con el
sentido (estimado, desestimado, inadmitido). **Hoy.** Las resoluciones se
enlazan y se muestran; no avisan. **Depende de.** Outbox. **Esfuerzo /
gate.** S · sin gate.

*Aceptación:*
- Evento `licitacion.recurso` con `sentido`; test por sentido.
- La oportunidad muestra el recurso en su cronología.

*Adopción:* propiedad `tipo=recurso` en la lectura de alertas.

#### F5.3 Avisos con nombre: anulación, desierto, ampliación de plazo, corrección de importe — P1

**Para quién.** Todos. **Qué.** Los cambios de expedientes seguidos (v2
S4.5) se clasifican en tipos con nombre y la campana los distingue con icono y
texto: «plazo ampliado al 12/10», «importe corregido de X a Y», «anulado».
**Hoy.** v2 S4.5 emite un cambio genérico. **Depende de.** v2 S4.5.
**Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- Catálogo tipado de subtipos derivados de `changed_fields` y `estado`; un
  cambio no clasificable cae a `cambio` genérico.
- El digest agrupa por subtipo.

*Adopción:* propiedad `tipo` en la lectura de alertas.

#### F5.4 «Qué cambió desde tu última visita» — P1

**Para quién.** Quien entra una vez al día. **Qué.** El Resumen abre con un
diff personal: expedientes seguidos que cambiaron, documentos nuevos,
oportunidades del equipo que se movieron, alertas de competidor; marcar todo
como visto. **Hoy.** Novedades de mercado con lecturas por usuario; no cubre
lo seguido ni al equipo. **Depende de.** Outbox y F5.1–F5.3. **Esfuerzo /
gate.** S · sin gate.

*Aceptación:*
- `GET /resumen/desde-mi-ultima-visita` con ámbito de organización y
  `last_seen` por usuario.
- Cero ítems → banda que lo dice, no vacía.

*Adopción:* propiedad `banda=desde_ultima_visita` en `espacio_abierto`.

#### F5.5 Reglas con vista previa de ruido — P2

**Para quién.** Quien recibe demasiado. **Qué.** Al crear o editar una
regla, serie de coincidencias por semana de las últimas ocho y aviso si
supera cincuenta por semana, con sugerencia de acotar. **Hoy.** `preview`
devuelve las coincidencias actuales sin serie. **Depende de.** Nada.
**Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- `POST /watchlist/rules/preview` gana `serie_semanal` (aditivo).
- Test de que el umbral de aviso es configurable y se declara.

*Adopción:* propiedad `ruido_avisado` en `regla_creada`.

#### F5.6 Silenciar y posponer — P2

**Para quién.** Quien tría. **Qué.** «Silenciar este expediente treinta
días» y «recordar en N días» en Radar y campana; el expediente reaparece al
vencer. **Hoy.** Hecho 18. **Depende de.** Nada. **Esfuerzo / gate.** S ·
**[§6]** migración (`radar_dismissals.hasta`), pre-autorizada.

*Aceptación:*
- El scoring excluye descartes vigentes y reincorpora los vencidos (test de
  reaparición).
- El recordatorio llega como alerta en la fecha elegida.

*Adopción:* propiedad `accion=silenciar|posponer` en `radar_triaje`.

### F6 — Configurar y compartir

#### F6.1 Ámbito de mercado de la organización — P0

**Para quién.** Owner y admin. **Qué.** CPVs, CCAA, rango de importe, tipos
de órgano y procedimientos excluidos a nivel de organización; el Radar y las
reglas lo heredan cuando el usuario no filtra, con precedencia declarada:
perfil personal, luego organización, luego global. **Hoy.** Hecho 15.
**Depende de.** Nada; F1.7 para los procedimientos. **Esfuerzo / gate.** M ·
**[§6]** migración, pre-autorizada.

*Aceptación:*
- `OrganizationSettings` gana los campos; contrato tipado.
- El Radar muestra «ámbito: organización» o «ámbito: tu perfil» en la
  cabecera, como hoy muestra el alcance.
- Test de precedencia con las tres capas.

*Adopción:* `perfil_configurado` gana `nivel ∈ {personal, organizacion}`.

#### F6.2 Reportar un dato incorrecto — P1

**Para quién.** Todos. **Qué.** Desde la ficha, «reportar» con tipo
(tecnología errónea, CCAA errónea, duplicado, importe, adjudicatario, otro);
cada tipo llega a la cola que ya existe (feedback ML, revisión de dedupe,
revisión de empresas) y el usuario ve el estado. **Hoy.** El feedback de
tecnología existe; el resto no tiene entrada. **Depende de.** Nada.
**Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- `POST /licitaciones/{id}/reportes` tipado; enrutado por tipo con test.
- La vista Calidad de datos muestra reportes abiertos por tipo.

*Adopción:* evento nuevo `dato_reportado` con `tipo`.

#### F6.3 Exportación a CRM (D35) — P1

**Para quién.** Comercial que vive en el CRM. **Qué.** Plantilla de webhook
`crm_generic` (cuenta = órgano, importe, etapa, fecha de cierre, responsable)
sobre las plantillas de v2 S4.3, más export CSV con mapeo documentado para
Salesforce y Dynamics. **Hoy.** Nada. **Depende de.** v2 S4.2 y S4.3.
**Esfuerzo / gate.** S · **[§6]** `.env.example` si hace falta, pre-autorizado.

*Aceptación:*
- Fixture de payload validada; el mapeo vive en `docs/integraciones/crm.md`.
- Un cambio de etapa dispara el webhook una sola vez (idempotencia del
  outbox).

*Adopción:* `export_lanzado` con `formato=crm`.

#### F6.4 Plantillas de organización para nuevos miembros — P2

**Para quién.** Admin que incorpora gente. **Qué.** Reglas, vistas guardadas
y etiquetas por defecto que un nuevo miembro recibe al aceptar la invitación
(copias, no referencias). **Hoy.** Cada miembro empieza vacío. **Depende de.**
Invitaciones (v2 S1.1). **Esfuerzo / gate.** S · **[§6]** migración,
pre-autorizada.

*Aceptación:*
- Al activar la membresía se crean las copias una sola vez (idempotente).
- El miembro puede borrar lo copiado sin afectar a la plantilla.

*Adopción:* propiedad `origen=plantilla_org` en `regla_creada` y
`vista_guardada`.

#### F6.5 Hub público por órgano — P2

**Para quién.** Quien llega desde un buscador. **Qué.** `/licitaciones/organo/[slug]`
con los anuncios del órgano, misma allowlist que el resto de la superficie
pública. **Hoy.** Hecho 16. **Depende de.** Maestro de órganos (C1.2).
**Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- `scripts/check_public_surface.py` sigue en verde; el hub no expone nada
  derivado.
- `seo.spec.ts` cubre la ruta; sitemap incluye los hubs con más de diez
  anuncios.

*Adopción:* ninguna (superficie pública, telemetría ya existente).

#### F6.6 Boletín público (D36) — P2, solo si D36 lo aprueba

**Para quién.** Captación. **Qué.** Digest público semanal por CCAA y CPV,
con alta y baja por enlace firmado. **Hoy.** Nada. **Depende de.** D36, v2
S1.3 y T6. **Esfuerzo / gate.** M · **[§6]** migración de suscriptores.

*Aceptación:* las de T6 más política de privacidad enlazada en el alta y
baja de un clic.

---

## 4. Métricas de cierre del plan

Se consideran cumplidas cuando el comando indicado las reproduce.

| Métrica | Hoy (2026-09-05) | Objetivo | Cómo medir |
|---|---|---|---|
| Filtros del listado | 12 parámetros, sin importe, CPV, órgano, provincia ni procedimiento | los ocho de F1.1 | OpenAPI de `GET /licitaciones` |
| Tipos de resultado en ⌘K | 1 (expediente) | 4 | `GET /search/global` |
| Tarjetas del Radar con explicación en texto | 0 % | 100 % | `ScoredOpportunity.explicacion` |
| Órganos seguibles como cuenta | no | sí | `POST /cuentas` |
| Familias de la ficha | 13 | 17 (fórmula, documentos, tarifas, presupuesto) | `shared/tender_facts.py` |
| Simulador de puntuación | no | sí, con golden de 10 pliegos | `GET /licitaciones/{id}/simulador` |
| Cierres `lost` con motivo codificado | 0 % | 100 % de los nuevos | `outcome_reason_code` |
| Funciones de `services/partners.py` sin consumidor | 3 | 0 | grep de callers |
| Oportunidades con fecha prevista de adjudicación | 0 % | todas con órgano con `n ≥ 5` | `PursuitSummary.expected_award_date` |
| Contratos ganados con seguimiento de fin | 0 | todos los `won` | vista Cartera |
| Tipos de aviso con nombre | 2 (vencimiento, coincidencia de regla) | ≥ 8 | catálogo de eventos |
| Eventos de telemetría del catálogo | 14 | 14 + 8 nuevos, ninguno con identificador | `web/src/lib/analytics.ts` |
| Campos de ámbito de la organización | 1 (`tecnologias`) | 6 | `OrganizationSettings` |

## 5. Orden de entrega

Cuatro entregas, cada una cerrable sola. Dentro de cada una los ítems son
paralelos salvo que se indique.

1. **Entrega 1 — Ver lo que ya sabemos** (todo S, sin dependencias
   externas): F1.3, F1.7, F1.8, F4.4, F2.5, F2.7, F5.5, F5.6, F6.2. Diez
   días de agente; ninguna espera a los otros planes.
2. **Entrega 2 — Decidir mejor** (P0 del recorrido de calificación): F1.1,
   F2.2, F2.3, F2.4, F3.1, F4.1, F6.1. F2.2 y F2.4 comparten el golden de
   fichas con C5.1 del complementario y deben coordinarse con él.
3. **Entrega 3 — Cuentas y cartera** (necesita v2 O0, S4.1 y, para el
   enlace estable, C1.2): F1.5, F4.3, F5.1, F5.2, F5.3, F5.4, F3.4, F4.2.
4. **Entrega 4 — Equipo y salida** (necesita v2 S1.1, S4.3 y C6.1): F1.2,
   F1.6, F2.1 (tras D32), F2.6, F2.8, F3.2, F3.3, F3.5, F4.5, F4.6, F6.3,
   F6.4, F6.5, F6.6 (si D36).

Cada entrega cierra con `make check`, `make check-api-contract`, `make
web-test`, `make check-frontend-invariants`, E2E en CI, el catálogo de
telemetría actualizado y el backlog al día. Un ítem sin verificar no se marca
hecho.

## 6. Lo que NO se hace

- **Backup y restore drill.** Fuera por decisión del mantenedor.
- **Prosa de oferta generada por IA.** Solo esquemas con citas (D33). El
  producto vende confianza en el dato; no va a ofrecer párrafos.
- **Probabilidad de ganar.** Sigue bloqueada por `WinProbabilityGate`; el
  simulador de F2.2 da puntos, no probabilidades.
- **Hub público por tecnología.** La política de la superficie pública
  excluye campos derivados; cambiarla es una decisión del propietario, no una
  funcionalidad.
- **Conectores nativos de CRM** antes de que una organización nombre el suyo
  (D35).
- **App nativa y web push.** Como en el complementario: no hasta que existan
  preferencias y demanda medida.
- **Cortes analíticos nuevos en Mercado.** Los dos espacios nuevos (Cuentas,
  Dirección) absorben vistas existentes y añaden acción, no un corte más.
- **Scraping de portales sin datos abiertos.** La cobertura la decide D16 del
  complementario; este plan no abre fuentes.
