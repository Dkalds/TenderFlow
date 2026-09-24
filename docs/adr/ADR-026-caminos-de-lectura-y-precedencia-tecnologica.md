# ADR-026 — Caminos de lectura analítica y precedencia de la señal tecnológica

- **Estado:** aceptado
- **Fecha:** 2026-09-03
- **Supersede parcialmente:** [ADR-023](ADR-023-computo-en-vivo-agregacion-sql.md)
  (solo su diagrama de caminos de lectura, que quedó incompleto)
- **Relacionado:** [ADR-013](ADR-013-jerarquia-materializaciones-analiticas.md),
  [ADR-017](ADR-017-camino-lectura-analitico.md) (ambos ya superados),
  [ADR-022](ADR-022-frontera-de-persistencia.md),
  [ADR-024](ADR-024-services-biblioteca-no-frontera.md)

---

## Contexto

La revisión de arquitectura del 2026-09-02 encontró dos mapas equivocados, y
ambos tenían la misma consecuencia: alguien que lee la documentación para
decidir dónde tocar, toca donde no es.

**1. El diagrama canónico de caminos de lectura dibuja tres, y hay seis.**
ADR-023 §«camino canónico» describe `mat_clusters`, `kpi_snapshots` y el cómputo
en vivo. No menciona `licitaciones_canonicas`, la vista materializada que
alimenta toda la superficie pública indexable, creada en `v94` y redefinida en
`v98`. Un `grep` de `mv_licitaciones_canonicas` o `MATERIALIZED` sobre `docs/`
no devolvía nada. Es, además, el camino más frágil de los seis: su ausencia de
índice tumbó la superficie pública entera el 2026-08-28, y su contrato de
frescura (4 h) vivía **solo** en un comentario de
`db/repositories/publico.py`.

**2. La señal tecnológica tiene cinco productores y ninguna precedencia
escrita.** `licitaciones.tecnologia` —la columna que decide qué entra en el
universo publicable— la escriben **únicamente** los parsers, desde el regex de
`config/keywords.py`. El clasificador SAP, el multi-etiqueta, el etiquetado por
LLM y la señal extraída de pliegos escriben en un juego de columnas paralelo
(`ml_tecnologias`, `ml_proba_max`, `ml_tech_principal`). Consecuencia medible:
un expediente que el LLM etiqueta con confianza como tecnológico seguía fuera
del universo porque `tecnologia IS NULL`. Había precedencia documentada para las
columnas `ml_*` (en `scheduler/pipeline_runs.py`), pero era la del carril
sombra, no la del dato que gobierna la visibilidad.

---

## Decisión

### A. Los seis caminos de lectura, con su dueño y su contrato de frescura

| # | Camino | Implementación | Frescura | Cuándo usarlo |
|---|---|---|---|---|
| 1 | **SQL en vivo** | `db/repositories/aggregates.py` → `services/analytics/*` → `/api/v1/analytics/*` | tiempo real | Por defecto. Cualquier agregado con filtros del usuario. |
| 2 | **SQL acotado + pandas** | `db/repositories/adjudicaciones.py::load_*` → `services/analytics/competitors.py` | tiempo real | **Solo** cuando la transformación no es expresable en SQL (resolución de identidad de empresa por componentes conexos). Obligatorio `LIMIT` en la query y alcance declarado en el resultado. |
| 3 | **Snapshot `kpi_snapshots`** | `scheduler/kpi_precompute.py` → `db/repositories/kpi_snapshots.py` | por ejecución del cierre (≤ 4 h) | Camino rápido del overview **sin filtros**. Es también la señal de frescura que lee `scheduler/healthcheck.py`. |
| 4 | **Tabla materializada `mat_clusters`** | `scheduler/aggregates_precompute.py` → `AggregateRepository.load_mat_clusters` | por ejecución del cierre | Clustering, cuyo cálculo no cabe en una request. |
| 5 | **Vista materializada `licitaciones_canonicas`** | `v94` → `v98` → `v99`; refresco en `db/repositories/publico.py` | ≤ 4 h, vigilada por `canonicas_frescas` / `canonicas_tamano` en `ops_events` | **Toda** la superficie pública indexable: fichas, hubs, sitemap, portada. |
| 6 | **DuckDB → Parquet** | `db/analytics.py` + `shared/parquet_manifest.py`, disparado por `kpi_precompute --export-parquet` | por ejecución | Exportación analítica histórica. Nunca en el camino de una request HTTP. |

**Regla que gobierna a los seis:** una request HTTP usa 1, 2, 3 o 5. Los caminos
4 y 6 son de proceso batch. Ningún camino nuevo se añade sin actualizar esta
tabla.

**Consecuencia operativa que hay que recordar:** una vista materializada
**congela su consulta en el momento de crearse**; `REFRESH` no relee el código.
Por eso cualquier cambio del predicado que la define (`_publicable_sql`,
`universo_tecnologico_sql`) exige una **revisión Alembic nueva** que la
reconstruya, y la reconstrucción se hace construyendo la vista nueva al lado y
permutando con `DROP` + `RENAME` —milisegundos— en vez de tirarla y dejar la
superficie pública sin vista durante la reconstrucción.

### B. Precedencia de la señal tecnológica

Cuando varias fuentes opinan sobre la tecnología de un expediente, el orden es:

1. **Keyword** (`licitaciones.tecnologia`, escrito por los parsers desde
   `config/keywords.py`). Es la señal más conservadora y la única que existe en
   el momento de la ingesta.
2. **Modelo multi-etiqueta** (`ml_tecnologias`, `ml_proba_max`), por encima de
   su umbral de decisión.
3. **Etiquetado por LLM** (`licitacion_tecnologia_pliego`, `method='llm'`),
   fundido hacia `ml_tecnologias`.
4. **Señal extraída del pliego** (`licitacion_tecnologia_score`, por encima de
   `PLIEGO_TECH_MIN_SCORE`).

Reglas derivadas, todas ellas verificables en test:

- **El merge nunca borra** una tecnología ya predicha: solo añade. Una fuente
  posterior puede subir el score de una etiqueta, no retirarla.
- **`ml_*` pertenece al plano de ML**, no a la ingesta. El upsert las escribe en
  `INSERT` y no las sobreescribe en re-ingesta; de lo contrario cada pasada del
  scraper revierte el trabajo de los cuatro productores de arriba y hace falta
  un barrido de reparación tras cada pasada para deshacer el daño.
- **El universo publicable admite las cuatro señales**, no solo la primera
  (revisión `v99`). El criterio deja de ser «el regex encontró una palabra» y
  pasa a ser «alguna fuente con umbral declarado dice que esto es tecnología».
- Una tecnología presente en `ml_tecnologias` **sin fila de score** vale `0.0`,
  no es un error: las dos columnas viven en tablas distintas y nada garantiza
  que la primera esté contenida en la segunda.

### C. Un predicado, un dueño

Los predicados que definen el universo (`universo_tecnologico_sql`,
`TECHNOLOGY_OBSERVED_SQL`), la exclusión de duplicados
(`exclude_duplicados_sql`), la ventana de expediente abierto
(`shared/estados.py::abierta_sql`) y la clave canónica viven en **un solo
sitio** y se importan. No se copian.

El motivo no es estético. `db/sql_fragments.py` documenta que la cadena del
predicado de universo debe ser **byte-idéntica** para que Postgres use el índice
parcial de `v84`; una copia que normalice un espacio deja de usar el índice sin
que falle nada. Y una copia que se quede atrás produce lo que se midió el
2026-09-02: `kpi_snapshots` calculado sobre un universo más estrecho que el de
la superficie pública, es decir, dos respuestas distintas a la misma pregunta
según por qué endpoint entres.

Un test escanea el árbol y falla si el literal reaparece fuera de su dueño.

---

## Alternativas descartadas

- **Dejar que cada consumidor elija su universo.** Es el estado que produjo el
  desajuste; la flexibilidad no la pedía nadie.
- **Unificar los seis caminos en uno.** Tienen razones de existir distintas y
  medidas: el anti-join canónico agrupado costaba 9,1 s frente a ~200 s sin
  agrupar, y el clustering no cabe en una request. Lo que faltaba era el mapa,
  no la unificación.
- **Que el LLM escriba directamente `licitaciones.tecnologia`.** Mezcla la
  señal más barata de revertir con la columna que gobierna la visibilidad
  pública y el linaje de ingesta. El carril `ml_*` con precedencia declarada
  conserva la trazabilidad de quién dijo qué.

## Consecuencias

- La superficie pública crece al admitir señal de ML: **es el objetivo**, y hay
  que medir el delta contra BD real tras aplicar `v99`, no darlo por bueno.
- `kpi_snapshots` cambia de cifras al pasar al universo ancho. Es una corrección,
  no una regresión, pero se anuncia: series anteriores y posteriores no son
  comparables sin declararlo.
- Cualquier ADR futuro que añada un camino de lectura actualiza la tabla de §A
  en el mismo cambio.

---

## Addendum 2026-09-06 — Qué se hace con una republicación (D23)

Lo pedía el plan complementario (C4.2): `detect_republicaciones` marcaba
**siempre** `pending` y ADR-026 no decía qué hacer con esas filas, así que cada
superficie hacía una cosa distinta sin haberlo decidido.

### El hecho, medido

Un contrato reemitido produce varias filas: TED acuña un `publication-number`
por anuncio —uno por corrigendo, otro por la adjudicación— y el conector de
PSCP cae al `id` de la fila cuando el registro no trae `codi_expedient`.
`detect_republicaciones` las empareja por órgano + CPV4 + año-mes + título.

Antes de este addendum:

| Superficie | Qué hacía con una republicación |
|---|---|
| Superficie pública | La colapsaba, pero **por otro camino**: `fila_canonica_sql` agrupa por `clave_canonica_sql`, que es la misma clave que `republicacion_key`. Correcto por coincidencia, no por decisión. |
| Radar | La mostraba **N veces**: `scoring_candidates` no excluía ningún duplicado, ni siquiera los `confirmed`. |
| Analítica competitiva | La contaba (solo excluye `confirmed`), y así debe seguir. |
| Ficha de detalle | La servía sin decir que lo era. |

### La regla

**Presentación esconde; métrica cuenta; la ficha avisa.**

| Superficie | Regla | Implementación |
|---|---|---|
| Radar, listados | Esconde `pending` **y** `confirmed` | `exclude_duplicados_presentacion_sql` |
| Superficie pública | Colapsa por clave canónica | `fila_canonica_sql` (sin cambios) |
| Cuota, HHI, bajas | Esconde **solo** `confirmed` | `exclude_duplicados_sql` (sin cambios) |
| Ficha de detalle | La sirve **y lo dice** | `LicitacionDetail.republicacion_de` |

### Por qué esta asimetría y no una regla única

Porque los dos errores no cuestan lo mismo.

- **Esconder de más en el Radar** cuesta que un expediente aparezca una vez en
  vez de tres. El original sigue publicado y la ficha del duplicado sigue
  respondiendo.
- **Esconder de más en una métrica competitiva** retira un contrato de la cuota
  de mercado de una empresa. Si el par resulta ser un falso positivo —dos lotes
  de un acuerdo marco comparten órgano, CPV4, mes y título con facilidad— la
  métrica queda mal para siempre y nadie se entera.

Esa diferencia es la razón por la que `detect_republicaciones` no puede marcar
`confirmed` y a la vez sí puede gobernar lo que se enseña. Dos preguntas
distintas, dos umbrales de evidencia distintos.

### Por qué la ficha no devuelve 404

Un enlace guardado, un resultado de Google o un favorito no pueden romperse
porque un job nocturno decidiera que esa fila es un duplicado —sobre todo
tratándose de `pending`, que por definición nadie ha confirmado—. La ficha
responde, y `republicacion_de` le da al usuario el id de la canónica para que
juzgue por sí mismo.

---

## Addendum 2026-09-18 — El resumen `ml_*` se deriva (T3, `v136`)

§B decía que el LLM y el pliego «se funden hacia `ml_tecnologias`». Desde
`v136_tecnologia_verdad_unica` ese «fundir» ya no es un `UPDATE`: todos los
productores escriben filas de `licitacion_tecnologia_score` y el trigger
`trg_lts_derivar_ml` deriva `ml_tecnologias`, `ml_tech_principal` y
`ml_proba_max` (predicha = `probabilidad >= threshold_aplicado`). La precedencia
de §B no cambia, y tampoco la regla «el merge nunca borra»: una etiqueta del
CSV sin fila de score se **adopta** con umbral igual a su score antes de que el
trigger pueda perderla.

`licitaciones.tecnologia` queda **fuera** de la derivación: es la señal 1 de
§B y no nace de esta tabla. Ni §A ni §C cambian — la columna que lee
`universo_tecnologico_sql` es la misma, así que la vista materializada no se
reconstruye.

---

## Addendum 2026-09-24 — TED frente a la plataforma del comprador

### El hecho, medido

El mismo contrato salía dos veces: la fila de PLACSP (o PSCP) y la de TED que lo
republica en el DOUE. Ninguno de los dos detectores de D23 podía verlo:

- `detect_duplicates` empareja por expediente natural, y el de una fila TED es su
  `publication-number`, no el expediente del comprador.
- La clave de reemisión —y con ella `fila_canonica_sql` y la vista
  `licitaciones_canonicas`— compara el título, y el de TED se guardaba como
  «España – {etiqueta del CPV} – {título}». Ese prefijo lo compone TED, no el
  comprador: estaba en el 100 % de 300 avisos medidos.

Medido el 2026-09-24 sobre los 99 expedientes de PLACSP del 2026-09-08 que se
publicaron también en el DOUE: el BT-22 del aviso TED es el `ContractFolderID` de
PLACSP en 98 de ellos, pero BT-22 **no es único** («01/2026» lo comparten decenas
de órganos). El `idEvl` del deeplink de PLACSP sí lo es: en los 157 pares que lo
traían, cada discrepancia de `idEvl` era un falso positivo de BT-22.

### La regla

| Referencia que publica el aviso TED | Condición | Marca |
|---|---|---|
| `idEvl` del deeplink de PLACSP (BT-15) | basta | `confirmed` |
| BT-22 = expediente natural de otra fuente | y mismo órgano **o** mismo título | `confirmed` |
| BT-22 solo | — | ninguna |

En esos pares **la canónica es siempre la otra fuente** —PLACSP antes que las
demás, contando `bulk_YYYYMM` como PLACSP—: TED republica, no origina, y lo hace
con menos detalle (sin lotes ni pliegos). Es `confirmed` y no `pending` porque la
evidencia es un identificador y no una clave heurística, y porque el aviso de
adjudicación de TED trae su propia adjudicación: sin la marca, la cuota de
mercado contaba el contrato dos veces.

La canónica tiene que seguir visible: solo es candidata una fila publicable y
sin marca previa de duplicado, para que esconder la de TED no se lleve nunca el
contrato entero ni cierre un ciclo de dos filas escondiéndose mutuamente.

Implementación: `services.dedupe.detect_duplicados_por_referencia`, alimentado por
`TedConnector.referencias_cruzadas()` desde `scraper/connectors/base.py`.

### Lo que queda fuera

- **El orden de la vista canónica.** `_criterios_canonicos_sql`, congelado en
  `v102`, sigue siendo «`fuente = 'placsp'` primero, luego la más antigua». Un par
  sin referencia explícita que colapse por clave puede seguir eligiendo la fila
  TED si es la más antigua, y `bulk_YYYYMM` sigue sin contar como PLACSP.
  Cambiarlo exige una migración que reconstruya la vista.
- **BT-22 y el `idEvl` no son columnas.** El emparejamiento ocurre mientras el
  conector re-lee su ventana de 14 días; pasada la ventana, un backfill
  (`python -m scraper.connectors.ted --desde YYYYMMDD`) re-lee y empareja.
- **La ficha pública de la fila TED marcada responde 404**, porque su predicado
  (`_publicable_sql`) excluye los duplicados `confirmed`. Es la regla que ya
  regía para cualquier duplicado confirmado; una redirección 301 a la canónica
  conservaría mejor lo ya indexado.
