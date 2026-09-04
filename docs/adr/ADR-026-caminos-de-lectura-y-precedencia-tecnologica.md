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
