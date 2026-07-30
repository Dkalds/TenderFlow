# Plan de ejecución de producto — TenderFlow

**Fecha:** 2026-07-30
**Objetivo:** convertir TenderFlow de observatorio analítico en un sistema de
decisión y ejecución para equipos de licitación.

## 1. Resultado que se quiere dirigir

La métrica principal deja de ser una métrica interna de recuperación o de
cobertura de código. TenderFlow debe poder medir:

- euros adjudicados en `pursuits` gestionadas en la plataforma;
- tasa de victoria sobre ofertas presentadas;
- conversión desde oportunidad identificada hasta oferta presentada;
- tiempo desde identificación hasta decisión go/no-go;
- calibración de la recomendación de precio (Brier score y curvas por decil);
- porcentaje de campos de pliego con evidencia verificable;
- frescura y cobertura por fuente.

Las métricas se segmentarán por organización y periodo. Ningún agregado de
mercado se presentará sin universo observado, denominador y linaje.

## 2. Correcciones respecto al diagnóstico de partida

El diagnóstico es útil como dirección de producto, pero algunas referencias ya
no describen el estado actual del repositorio:

- `scraper/pipeline.py` está deprecado para nuevas fuentes; la ingesta de
  producción usa `scraper/connectors/`.
- La exportación y el borrado GDPR de watchlist, reglas, perfil y
  notificaciones se corrigieron el 2026-07-13 y tienen pruebas de regresión.
- `db/analytics.py` vuelve a exportar snapshots Parquet con manifest y dispone
  de pruebas.
- Ya existen ingesta de documentos, texto extraído, chunks, embeddings y
  retrieval híbrido. Sigue pendiente la parte de producto: persistencia de una
  evidencia reprocesable y extracción estructurada de la ficha del pliego.
- Las predicciones existentes incluyen `model_version`, pero las filas de
  ingesta y los agregados de mercado aún no expresan de forma uniforme el
  universo observado, el denominador y la versión del filtro.

Por tanto, las correcciones GDPR y OLAP pasan a ser controles de regresión, no
entregas nuevas.

## 3. Principios de implementación

1. **Outcome antes que heurística.** Primero se captura la decisión y el
   resultado; después se entrena y calibra.
2. **Organización desde el origen.** Todo dato colaborativo nuevo nace con
   `organization_id`; no se crea otra entidad personal que haya que migrar.
3. **Evidencia antes que chat.** Un campo extraído incluye confianza y referencia
   verificable, o queda vacío.
4. **Probabilidad solo si está calibrada.** Hasta disponer de labels suficientes,
   la UI muestra distribuciones históricas y escenarios, no una falsa
   `P(ganar)`.
5. **Analítica con alcance explícito.** Cada cuota, HHI o concentración declara
   universo, denominador, ventana, fuente y versión de filtro/modelo.
6. **Migraciones aditivas.** No se reescriben revisiones existentes. Los cambios
   se despliegan con compatibilidad hacia atrás y retirada posterior.
7. **Una entrega vertical por fase.** Cada fase incluye persistencia, servicio,
   contrato API, UI, métricas y pruebas.

## 4. Roadmap ejecutable

### Fase 1 — Fundamento colaborativo y `pursuits` (P0)

**Resultado de usuario:** un equipo puede convertir una licitación en
oportunidad, asignarla, decidir go/no-go, registrar la oferta y cerrar el
resultado.

**Persistencia**

- `organizations`: cuenta de trabajo y configuración básica.
- `organization_memberships`: usuario, rol (`owner`, `admin`, `member`,
  `viewer`) y estado.
- `pursuits`: una oportunidad por `(organization_id, licitacion_id)`, con
  responsable, estado, decisión, motivo, precio ofertado, resultado y fechas.
- `pursuit_events`: historial append-only de cambios para auditoría y métricas
  de ciclo.
- Organización personal inicial para cada usuario existente, sin mover todavía
  datos históricos de watchlist.

Estados canónicos:

`identified → qualifying → go_no_go → preparing → submitted → won|lost|withdrawn`

La decisión (`pending|go|no_go`) y el resultado
(`pending|won|lost|cancelled`) son dimensiones separadas del estado. Esto evita
inferir decisiones de negocio a partir de etiquetas de interfaz.

**API y dominio**

- DTOs Pydantic estrictos para crear, actualizar, listar y resumir `pursuits`.
- Repositorio fino en `db/repositories/pursuits.py`.
- Servicio en `services/pursuits.py` con validación de transiciones y permisos.
- Endpoints:
  - `POST /api/v1/pursuits`
  - `GET /api/v1/pursuits`
  - `GET /api/v1/pursuits/{id}`
  - `PATCH /api/v1/pursuits/{id}`
  - `GET /api/v1/pursuits/metrics`
- Eventos de dominio para cambios relevantes, sin duplicación al reintentar.
- Exportación y borrado/anonimización GDPR ampliados a membresías, `pursuits` y
  eventos según su naturaleza personal o corporativa.

**Web**

- `Radar`: ranking actual con acciones `Descartar`, `Seguir` y `Abrir
  oportunidad`.
- `Oportunidades`: vista operativa por estado, responsable y vencimiento.
- Ficha de oportunidad con decisión, motivo, precio y resultado.
- El favorito actual sigue funcionando durante la transición; abrir una
  oportunidad es una acción distinta y explícita.

**Métricas de producto**

- `pursuits_identified`, `pursuits_submitted`, `pursuits_won`,
  `pursuits_lost`, `win_rate`, `awarded_amount_eur`,
  `median_decision_time_hours`.
- Resumen reproducible desde código mediante `make product-status`.

**Aceptación**

- Dos miembros de una organización ven el mismo `pursuit`; un tercero ajeno no.
- Las transiciones inválidas devuelven error de dominio tipado.
- Crear dos veces la misma oportunidad no duplica filas.
- Ganada/perdida exige oferta presentada; `won` exige importe adjudicado o
  justificación de ausencia.
- Toda mutación relevante genera exactamente un evento.
- API, UI y export GDPR están cubiertas por pruebas.

### Fase 2 — Organización como scope real (P0)

**Resultado de usuario:** watchlists, filtros, perfiles y notificaciones se
comparten de forma controlada dentro del equipo.

- Selector de organización activa y administración de miembros/roles.
- `organization_id` aditivo en `watchlist_items`, `watchlist_rules`,
  `saved_filters`, `user_profiles` y preferencias de notificación.
- Visibilidad `private|organization` donde tenga sentido.
- Backfill determinista desde la organización personal de Fase 1.
- Lectura dual temporal y posterior retirada del scope `user_key`.
- Invitaciones y cambios de rol auditados.

No se cambia el mecanismo de autenticación. La autorización de organización se
resuelve en servicio y repositorio, nunca en el frontend.

### Fase 3 — Ficha estructurada del pliego (P0)

**Resultado de usuario:** la oportunidad muestra qué exige el pliego y dónde lo
dice.

- Persistencia reprocesable: binario en almacenamiento de objetos o, como
  mínimo, texto por página con offsets y hash de contenido.
- `TenderFactSheet` Pydantic estricto:
  - criterios de adjudicación y pesos;
  - solvencia técnica y económica;
  - garantías y penalizaciones;
  - subcontratación;
  - equipo/perfiles requeridos;
  - prórrogas y fechas críticas.
- Por campo: `value`, `confidence`, `evidence` (documento, página/offset y
  extracto breve), `extraction_version`.
- Estados `pending|extracted|needs_review|failed`; los campos desconocidos son
  `null`.
- Revisión humana y reextracción versionada.
- El go/no-go consume la ficha; el chat enlaza a la misma evidencia.

### Fase 4 — Precio y probabilidad de victoria (P1)

**Resultado de usuario:** comparar escenarios de precio con evidencia y
calibración visibles.

1. V1 inmediata: distribución histórica de bajas por órgano, CPV, importe y
   competencia, con tamaño muestral e intervalos.
2. Captura de `offer_price_eur`, precio adjudicado y outcome desde Fase 1.
3. Dataset temporal sin fuga de información y validación por segmento.
4. Curva monotónica precio/descuento → probabilidad, solo para segmentos que
   superen el mínimo de muestra y calibración.
5. UI de escenarios (no un único “precio mágico”) con rango, incertidumbre,
   `model_version`, fecha y calidad de calibración.

El modelo no se promociona por AUC solamente: exige Brier score, calibración por
decil y mejora frente al baseline histórico.

### Fase 5 — Cobertura y SLA de fuentes (P1)

**Resultado de usuario:** saber qué fuentes están al día y cuándo no confiar.

- Cablear TED en el workflow diario (requiere aprobación específica de
  `.github/workflows/`).
- Priorizar 3–4 conectores autonómicos por volumen TI y latencia observada.
- Registrar por fuente: cursor, última publicación vista, última ingesta
  exitosa, lag y errores.
- Endpoint y panel de SLA con `% <24h`, tendencia y banner de degradación.
- Alerta operativa cuando el cursor no avanza, aunque el job global quede verde.

### Fase 6 — Tres espacios de producto (P1)

**Resultado de usuario:** responder “a qué me presento esta semana y por qué”.

- **Radar:** descubrimiento personalizado y acción directa.
- **Oportunidad:** ficha 360, pliego, decisión, equipo, competencia y precio.
- **Mercado:** consulta analítica con alcance explícito.

La reducción es gradual: primero se agrupan rutas y navegación, luego se mide
uso y finalmente se retiran páginas redundantes. No se borran capacidades ni
tests sin aprobación expresa.

### Fase 7 — Universo y honestidad estadística (P0, en paralelo)

**Resultado de usuario:** una métrica defendible y reproducible.

- Linaje de ingesta: `source`, `observed_at`, `filter_version`,
  `classifier_model_version`, `inclusion_reason` y `analysis_universe`.
- Ingesta complementaria por NIF de empresas seguidas para adjudicaciones,
  separada del radar TI.
- DTO compartido `MetricScope` para cuota/HHI/concentración:
  `label`, `universe`, `denominator`, `window`, `sources`,
  `filter_version`, `model_version`, `computed_at`.
- Copy: “cuota dentro del segmento TI observado”, nunca “cuota de mercado”
  sin calificador.
- Series incompatibles por cambio de universo se separan o se marcan; no se
  unen silenciosamente.

### Fase 8 — Contratos y controles de regresión (P1)

- Reducir `dict[str, Any]` en operaciones públicas mediante DTOs explícitos.
- Mantener pruebas GDPR que fallen ante tablas o scopes inexistentes.
- Mantener el export OLAP y su manifest como gate.
- Añadir tests de contrato consumidor-proveedor que no se comparen únicamente
  contra un OpenAPI regenerado en el mismo cambio.

## 5. Dependencias y gates

| Gate | Fases | Motivo |
|---|---:|---|
| Aprobación para `db/alembic/` | 1, 2, 3, 7 | Regla explícita de `AGENTS.md` |
| Aprobación para workflows | 5 | Activa ingesta en producción |
| Aprobación para dependencias | 3, si se elige SDK de object storage | Cambio de `pyproject.toml` |
| Decisión de almacenamiento | 3 | Binario completo frente a texto por página |
| Muestra mínima de outcomes | 4 | Evita publicar probabilidades no defendibles |

Los gates no bloquean el diseño ni las pruebas puras, pero sí la mutación
correspondiente.

## 6. Secuencia de entrega

1. Migración fundacional + repositorios + servicios de Fase 1.
2. API y pruebas de autorización/transiciones.
3. Radar/Oportunidades y captura de outcome.
4. Métricas de producto y `make product-status`.
5. Scope organizativo del resto de datos.
6. Ficha del pliego.
7. Precio calibrado.
8. Cobertura/SLA, reorganización de IA y retirada gradual.

Cada fase cierra con `ruff`, `mypy`, tests unitarios, pruebas de contrato,
verificación de migración Postgres y actualización de `graphify`.

## 7. Estado de implementación (2026-07-30)

Las ocho fases quedan implementadas en una entrega vertical:

- organizaciones, membresías, aislamiento por tenant y `pursuits` con historial,
  go/no-go, oferta, resultado, GDPR y métricas de producto;
- scope organizativo en watchlists, reglas, filtros, perfiles y notificaciones,
  con selector de organización activa;
- ficha estructurada y versionada del pliego, texto por página con offsets,
  evidencia literal, revisión y estados de extracción;
- escenarios descriptivos de precio con muestra, cuantiles e incertidumbre; la
  probabilidad de victoria permanece bloqueada explícitamente hasta superar el
  gate de outcomes y calibración;
- SLA por fuente, panel de frescura e instrumentación común; TED, Galicia,
  Euskadi y el carril por NIF están conectados al workflow diario;
- navegación principal simplificada en Radar, Oportunidades y Mercado;
- linaje persistido, `MetricScope` y separación estricta entre el universo
  tecnológico y las adjudicaciones observadas por NIF, evitando doble conteo;
- OpenAPI y tipos web regenerados, pruebas de autorización, migraciones,
  conectores, métricas, RAG, pricing y contratos añadidas.

La cadena de schema es aditiva y conserva una única cabeza Alembic:
`v60_pg_missing_user_columns → v61 → v62 → v63 → v64`.
