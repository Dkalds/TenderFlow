# Puntuaciones del acta de adjudicación — diseño

- **Fecha:** 2026-11-01
- **Estado:** implementado (pendiente de CI y merge). Aprobado por secciones en
  el brainstorming del 2026-11-01 y el spec escrito el mismo día
- **Rama:** `claude/licitadores-puntuaciones-adjudicacion-cd972a`
- **Plan de implementación:** [2026-11-01-puntuaciones-acta.md](../plans/2026-11-01-puntuaciones-acta.md)
- **Justificación en el plan de foco:**
  [plan 2026-10](../../plans/2026-10-plan-foco-piloto.md), B6 («cerrar el
  resultado sin trabajo manual»): el motivo de pérdida sale propuesto a partir
  de los puntos publicados. No añade endpoint, espacio ni pantalla (D50).
- **Relacionado:** ADR-014 (sin evidencia no hay dato), ADR-022 (SQL en `db/`),
  ADR-028 (cola de trabajo), D37 (motivos de pérdida cerrados), S2.1
  (`organization_nifs` y cierre asistido)

## 1. Objetivo y alcance

**Lo pedido:** explotar las puntuaciones que obtiene cada licitador en las
resoluciones de adjudicación para calibrar dónde pierde la organización y por
cuánto.

**Decisiones tomadas en el brainstorming:**

| Pregunta | Decisión |
|---|---|
| Para qué primero | **Post-mortem de lo perdido**: en una oportunidad adjudicada, la nota de la organización frente a la del ganador, criterio a criterio |
| De qué expedientes se extrae con LLM | **Solo los que tienen oportunidad** (`pursuits`). Las referencias a las actas se guardan para todo PLACSP, así que ampliar después es quitar un filtro |
| Cómo se sabe cuál es la fila propia | **El sistema propone, la persona confirma**, como en el cierre asistido |
| Por dónde entra el acta | **Enfoque A**: parsear `GeneralDocument` en la ingesta, no descargar en el fetcher nocturno, extraer bajo demanda al adjudicarse |

**Fuera de alcance** (y por qué):

- PSCP y TED: su ingesta no trae `GeneralDocument`; serían otro conector.
- Extraer fuera de las oportunidades: decisión de alcance y coste.
- Backfill de las oportunidades ya cerradas: no pedido; las referencias llegan
  en las próximas pasadas o en una reingesta.
- OCR de actas escaneadas: el mismo límite que los pliegos (backlog).
- Perfil de competidor y «preparar la próxima»: usos posteriores que la tabla
  en filas deja abiertos sin migrar otra vez.

## 2. Lo que se midió antes de diseñar

- El XML CODICE de PLACSP trae `cac-place-ext:GeneralDocument/
  GeneralDocumentDocumentReference` con `cbc:DocumentTypeCode`
  (`GeneralContractDocuments-2.08`). En los fixtures de
  `tests/fixtures/placsp*`: el código **12** es siempre «Acta del órgano de
  asistencia» (9 de 9); los informes de valoración y las resoluciones llegan
  como **ZZZ** con nombre libre («Informe de valoración», «Informe criterios
  automaticos», «Adjudicación definitiva 0027»). Los códigos 8, 9, 10, 11 y 14
  son inicio, memoria, insuficiencia de medios, aprobación y ofertas anormales.
- `scraper/codice_parser.py::parse_document_references` solo lee
  `Legal/Technical/AdditionalDocumentReference`: hoy esos documentos se
  pierden. En producción hay unas 50 actas en `documentos`, todas de PSCP o de
  anexos sueltos.
- Un acta real (Ayuntamiento de Astillero, exp. 1611/2026, fixture 19) trae
  por lote una tabla con cada empresa, su nota por criterio («Informe técnico
  (sobre 30 puntos)», «Oferta económica (sobre 65 puntos)»), el total y las
  excluidas. La forma de la tabla varía por órgano: hace falta un LLM, no
  reglas.
- Volumen: ~1.000 licitaciones PLACSP adjudicadas al mes, ~75 % con
  documentos ya descargados. Con el alcance elegido el coste es de una o dos
  llamadas por oportunidad adjudicada.

## 3. Ingesta y descarga

### 3.1 Parser

`parse_document_references` recorre además
`cacext:ContractFolderStatus/cacext:GeneralDocument/
cacext:GeneralDocumentDocumentReference` y emite
`DocumentoReferencia(tipo="acta", …)` cuando:

- `DocumentTypeCode == "12"`, o
- `DocumentTypeCode == "ZZZ"` y el nombre (`cbc:FileName` o `cbc:ID`, misma
  precedencia que hoy) casa, tras `fold_text`, con
  `valoraci|criterios autom|adjudicaci|propuesta`.

El resto de `GeneralDocument` se ignora. URI, nombre y `source_hash` se tratan
igual que en los pliegos (hash normalizado sin espacios; sin URI, se descarta).

### 3.2 Migración

Una revisión nueva (requiere OK explícito, AGENTS.md §6) que:

1. Amplía el CHECK de `documentos.tipo` a `('legal', 'technical',
   'additional', 'acta')`.
2. Crea las dos tablas de §5.

### 3.3 Fetcher

La selección de pendientes de `db/repositories/documentos.py` (la consulta de
`status='pending'` priorizada) excluye `tipo='acta'`. Las actas quedan como
referencia `pending` y **no** se descargan en la pasada nocturna, ni entran en
chunks, embeddings, RAG ni en el selector de páginas de la ficha. Al
implementar se comprueba que RAG, la ficha y el recuento de pendientes de
salud (`COUNT(*) FILTER (WHERE status IN ('pending', 'downloaded'))`) filtran
por tipo o se les añade el filtro; si un recuento de salud las contara como
atasco, se excluyen también ahí.

## 4. Disparo y extracción

### 4.1 Disparo

`services/pursuit_awards.py::notify_detected_awards` (llamado desde
`scheduler/pipeline_runs.py` tras cada pasada) encola, además de avisar, un
job `puntuaciones_acta` (nuevo tipo en `services/jobs.py`) por cada expediente
con oportunidad, adjudicación conocida y alguna referencia `tipo='acta'`, que
no tenga fila en `acta_extracciones` con la versión vigente. Idempotente con
`job_activo(tipo, campo="licitacion_id", valor=…)`.

Lo consume el mismo plano que hoy consume la cola en la API (ADR-028 §G).

### 4.2 Job

`services/puntuaciones_acta.py` (nuevo):

1. Descarga y extrae páginas solo de las actas del expediente (como mucho 3
   documentos) reutilizando el fetcher y `documento_pages`. Variante acotada
   por tipo de `ensure_documents_ready`, no una copia.
2. Selecciona las páginas con tabla de puntuación por señales: «puntuación»,
   «total», «sobre N puntos», y los nombres de criterio de
   `licitacion_criterios_adjudicacion` del expediente.
3. Una llamada al LLM en modo extracción, **sin fallback de proveedor** (la
   fila guarda `model`), con un tope de tiempo propio: el backlog registra que
   una extracción de ficha puede colgar 15 minutos el hilo de la cola.
4. Valida la salida con Pydantic:
   `{lotes: [{lote, filas: [{licitador, criterios: [{nombre, puntos, maximo}],
   total, excluida, cita, pagina}]}]}`.
5. Cada fila se guarda **solo si su cita aparece en la página citada**,
   reutilizando la validación de citas de `services/rag/fact_sheet.py`
   (`_validated_evidence` y la normalización de citas, sin duplicarla; si hay
   que hacerla pública, se mueve, no se copia). Sin cita verificable no hay
   dato (ADR-014).
6. Escribe el resultado y el estado (§5).

| Situación | `status` |
|---|---|
| Al menos una fila con cita válida | `ok` |
| Hay acta pero ninguna fila sobrevive | `sin_tabla` |
| El expediente no tiene referencias `acta` | `sin_acta` (lo escribe el disparo, sin job) |
| Proveedor caído, respuesta vacía, descarga fallida | `error`; reintento con el backoff de la cola hasta `jobs_max_intentos` |

Un acta escaneada sin texto termina en `sin_tabla` con `error_detail` que lo
dice.

## 5. Almacenamiento

Todo el SQL en `db/repositories/puntuaciones_acta.py` (nuevo).

### `acta_extracciones`

Una fila por expediente. Evita repetir llamadas y dice qué enseñar.

| Columna | Tipo |
|---|---|
| `licitacion_id` | `text` PK |
| `status` | `text` CHECK (`ok`, `sin_tabla`, `sin_acta`, `error`) |
| `extraction_version` | `text` |
| `model` | `text` nulo |
| `documentos_leidos` | `integer` |
| `error_detail` | `text` nulo |
| `extracted_at` | `timestamptz` nulo |
| `updated_at` | `timestamptz` |

### `acta_puntuaciones`

Una fila por licitador × criterio × lote. En filas y no en JSON porque la fila
es la unidad que después se agrega por competidor.

| Columna | Tipo |
|---|---|
| `id` | `bigint` PK |
| `licitacion_id` | `text` |
| `lote_numero` | `text` nulo |
| `licitador_nombre` | `text` (tal como lo publica el acta) |
| `licitador_normalizado` | `text` (`services.normalization.normalize_company`) |
| `criterio` | `text` nulo — `NULL` es la fila del total |
| `puntos` | `double precision` nulo |
| `puntos_max` | `double precision` nulo |
| `es_precio` | `boolean` nulo |
| `excluida` | `boolean` |
| `documento_id` | `integer` FK `documentos(id)` |
| `pagina` | `integer` |
| `cita` | `text` |

Único: `(licitacion_id, COALESCE(lote_numero, ''), licitador_normalizado,
COALESCE(criterio, ''))`. La escritura borra y vuelve a insertar el expediente
entero en una transacción: repetir no duplica (invariante §3.2).

`es_precio`: primero se casa el criterio con `licitacion_criterios_adjudicacion`
del expediente (ya marca `es_precio`); si no casa, por el nombre («oferta
económica», «precio», «baja»); si tampoco, `NULL`.

## 6. Lo que ve la persona

### 6.1 DTO

En `shared/dto/pursuits.py`, todo tipado (invariante §3.5):

- `PursuitAdjudicacionDetectada.puntuaciones: PuntuacionesActa | None`.
- `PuntuacionesActa`: `estado` (`pendiente`, `ok`, `sin_tabla`, `sin_acta`,
  `error`) y `lotes: list[PuntuacionesLote]`.
- `PuntuacionesLote`: `lote_numero`, `filas: list[FilaPuntuacion]`,
  `fila_ganadora: int | None`, `ganadora_es_mayor_puntuacion: bool`,
  `fila_propia: int | None`, `fila_propia_confirmada: bool`,
  `diferencia: list[DiferenciaCriterio]` (vacía sin las dos filas) y
  `motivo_sugerido: PursuitOutcomeReasonCode | None`.
- `FilaPuntuacion`: `licitador`, `licitador_normalizado`, `total`, `excluida`,
  `criterios: list[CriterioPuntuado]` (`nombre`, `puntos`, `maximo`,
  `es_precio`, `documento_id`, `pagina`, `cita`).

`estado='pendiente'` cuando hay referencias `acta` y aún no hay fila en
`acta_extracciones`.

### 6.2 Fila ganadora

La fila cuyo `licitador_normalizado` casa con el adjudicatario publicado del
lote (`adjudicaciones.nombre` normalizado). Si ninguna casa, la de mayor total
entre las no excluidas, con `ganadora_es_mayor_puntuacion=True`: la interfaz
la rotula «mayor puntuación» y no «ganadora».

### 6.3 Fila propia

**Propuesta:** casamiento **exacto tras normalizar** entre
`licitador_normalizado` y los nombres conocidos de la organización:

- los nombres publicados en `adjudicaciones` para sus NIF
  (`organization_nifs`) y los de sus `empresa_id` (`IdentidadFiscal`),
- sus `empresa_aliases`,
- el nombre de la organización.

Si casa más de una fila o ninguna, no se propone nada: proponer la fila de
otra empresa es peor que no proponer, porque la persona siempre puede
marcarla.

**Confirmada:** `PursuitUpdate` gana `fila_acta: FilaActaRef | None`
(`lote_numero`, `licitador_normalizado`). `services/pursuits.py::update_pursuit`
lo valida contra las filas existentes (422 si no existe) y lo anota en el
ledger como evento `fila_acta_confirmada`; no toca columnas de `pursuits`. Al
leer, el último evento de ese lote manda sobre la propuesta. Sin endpoint
nuevo: la superficie de la API no cambia.

### 6.4 Diferencia y motivo propuesto

Con fila propia y ganadora: por criterio, `puntos_propios − puntos_ganador`
sobre `maximo`, y el total. `motivo_sugerido`:

- Si la propia es la ganadora o está excluida: `None`.
- Se suman las pérdidas (solo las diferencias negativas) en criterios
  `es_precio=True` y en el resto. Si la de precio es mayor: `precio`. Si la de
  no precio es mayor o igual y no es cero: `tecnica`. Si las dos son cero:
  `None`.
- Sin `es_precio` conocido en ningún criterio: `None`.

Al cerrar como perdida, la ficha preselecciona `motivo_sugerido` en el campo
de motivo (que sigue siendo obligatorio y editable). El sistema propone, la
persona decide.

### 6.5 Interfaz

En `web/src/components/pursuits/adjudicacion-detectada.tsx`, dentro del bloque
de adjudicación que ya existe:

- Una tabla por lote: licitador, puntos por criterio («sobre N»), total;
  excluidas al final y marcadas. La fila propia y la ganadora resaltadas, con
  texto y no solo color.
- Bajo la tabla, la diferencia: «Precio −18,5 de 65 · Técnica −2 de 30 · Total
  −20,5». Cada cifra enlaza a su página del acta.
- Sin fila propia confirmada: un botón «Esta es mi empresa» por fila (manda el
  `PATCH`). Con propuesta sin confirmar: «¿Es esta tu empresa?» con confirmar.
- Estados: `pendiente` «Leyendo el acta de la mesa»; `sin_acta` «PLACSP no
  publicó acta de mesa para este expediente»; `sin_tabla` «El acta no trae
  puntuaciones por licitador»; `error` «No se pudo leer el acta; se reintenta
  en la próxima pasada».
- Accesible: tabla con `<caption>` y cabeceras, foco visible en los botones,
  legible en móvil sin scroll lateral de página (la tabla hace scroll dentro de
  su contenedor).

## 7. Tests

- **Unit** (sin BD):
  - parser: fixture 19 (código 12 entra, 9/11/14 no) y uno con `ZZZ` que entra
    y otro `ZZZ` que no;
  - validación del JSON del modelo y de las citas sobre el texto del acta de
    Astillero guardado como fixture (`tests/fixtures/actas/`);
  - fila ganadora (por nombre y por mayor puntuación), fila propia (exacta,
    ambigua, ninguna), diferencia y motivo (precio, técnica, empate, sin
    `es_precio`, propia ganadora, propia excluida);
  - `es_precio` por criterios del pliego y por nombre.
- **Integration** (Postgres; solo en CI o WSL desde este equipo):
  - repositorio: reemplazo idempotente, unicidad, FK;
  - el fetcher no elige `tipo='acta'`;
  - `notify_detected_awards` encola una vez y escribe `sin_acta`;
  - `PATCH` con `fila_acta`: evento en el ledger, gana a la propuesta, 422 con
    fila inexistente.
- **Escenario CU-05** (`tests/test_escenario_oportunidad.py`): adjudicada →
  acta leída (LLM con stub) → confirmo mi fila → cierro perdida con el motivo
  propuesto.
- **Frontend**: `adjudicacion-detectada.test.tsx` con tabla, diferencia,
  botón, propuesta y los cuatro estados.

## 8. Docs y gates

- `docs/casos-de-uso.md`: CU-05 menciona el post-mortem; `make casos-uso`.
- `make schema-doc` (necesita BD migrada: CI o WSL) y `make status`.
- Cliente TS regenerado (`web/src/generated/api.d.ts`) y
  `make check-api-contract`.
- `make check-layers`: `services/puntuaciones_acta.py` importa de `db/`,
  `services/rag/` y `shared/`; nada sube.
- `docs/IMPROVEMENT_BACKLOG.md`: entrada con lo hecho y lo que queda (ampliar
  alcance, backfill, PSCP/TED, OCR).
- Sin ADR nuevo: no contradice ninguno. Sin entrada en `NUEVAS` de
  `check_api_surface`: no hay operación nueva.

## 9. Riesgos

- **Pocas oportunidades.** Hoy hay 16, una sola organización con NIF y una
  perdida cerrada a mano. El valor depende de que lleguen más; el coste
  también es mínimo mientras tanto.
- **Actas que no publican puntuaciones.** Muchas mesas publican solo la
  apertura o la clasificación sin notas: `sin_tabla` lo dice en vez de
  inventar.
- **Lotes que no casan** entre acta y adjudicación: se enseña la tabla sin
  diferencia ni motivo.
- **Nombres que no casan** para la fila propia: por diseño no se propone y la
  persona la marca.
