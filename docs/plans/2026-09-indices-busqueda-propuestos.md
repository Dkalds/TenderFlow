---
tags: [plan, rendimiento, migraciones, propuesta]
---

# Índices para la búsqueda `q` y el filtro de tecnología

**Estado: ESCRITAS el 2026-09-25, pendientes de aplicar.** Con el OK del
usuario (AGENTS.md §6) existen `v142_lic_tecnologia_tokens_gin` y
`v143_lic_busqueda_plegada_trgm` tal como se describen abajo, con su test en
`tests/test_indices_busqueda.py`. Se aplican a mano con `migrate.yml`, y hasta
entonces `/health/ready` informa `schema_revision: behind`, el smoke falla y el
preflight de `ml-scoring` no deja correr el job: **aplicarlas justo después de
mergear**. Antes de `v143`, medir `descripcion` (sección «Riesgo principal»); si
no cabe, sacar `v143` y elegir una de las alternativas.

La cabeza del repo, comprobada recorriendo `down_revision` el 2026-09-24, es
**`v141_tasas_anulacion_organo`**:

```
v141_tasas_anulacion_organo ← v138_notice_type_code ← v140_predicciones_baja_por_lote
  ← v135_user_id_pk_fase3 ← v136_tecnologia_verdad_unica ← v134_nucleo_tipado_indices
```

Las dos revisiones de abajo se encadenarían detrás: `v142` con
`down_revision = "v141_tasas_anulacion_organo"` y `v143` detrás de `v142`.
**Hay que volver a comprobar la cabeza el día que se escriban**: si entra otra
revisión antes, cambia el `down_revision`, no el contenido.

## El problema

`licitaciones` tiene ~1,64 M filas y 972 MB de heap. El pool de lectura de la
API son 12 conexiones con `statement_timeout` de 30 s. Dos filtros del
dashboard no tienen índice utilizable y cada uno convierte **todas** las
consultas del overview —una docena— en escaneos secuenciales:

| Filtro | Qué emite | Índice que hay hoy | Por qué no sirve |
|---|---|---|---|
| `q` | `lower(translate(col, 'áà…', 'aa…')) LIKE '%q%'` en `OR` sobre `titulo`, `descripcion`, `organo_contratacion` e `id_externo` | `idx_licitaciones_titulo_trgm` (`v50`): trigram sobre `titulo` **sin plegar** | La consulta no pregunta por `titulo`, pregunta por su versión plegada. Y aunque sirviera, un `OR` solo se resuelve con `BitmapOr` si **todas** sus ramas tienen índice: con tres de cuatro sigue siendo secuencial. |
| `tecnologia` | hasta hoy, `EXISTS (SELECT 1 FROM unnest(string_to_array(COALESCE(col, ''), ',')) … WHERE trim(code) IN (…))` en los agregados y cuatro `LIKE` por código en el listado | `idx_lic_tecnologia` (`v21`): btree de igualdad sobre el CSV crudo | La columna guarda `"SAP,SALESFORCE"`; la igualdad nunca fue la pregunta. El `unnest` es un subplan por fila sin índice posible. |

Con `psycopg` 3 hay además una trampa que no se ve en ningún test: el listado
compilaba `func.translate(col, FOLD_SRC, FOLD_DST)` con cadenas de Python, y
SQLAlchemy las convertía en **parámetros ligados**. La consulta llegaba como
`translate(licitaciones.titulo, $1, $2)`. Con un plan personalizado Postgres
pliega los `$n` a constantes y un índice de expresión podría casar, pero psycopg
prepara la sentencia tras cinco ejecuciones y, en cuanto el servidor pasa a plan
**genérico**, los `$n` siguen siendo parámetros y el índice deja de valer sin que
falle nada.

## Paso 1 — hecho en código, sin migración (esta rama)

1. **Las tablas de plegado son literales, en los dos caminos.**
   `db/sql_fragments.py` define `FOLD_SRC_SQL`/`FOLD_DST_SQL` (las dos tablas ya
   entre comillas, validadas al importar: ni `'`, ni `\`, ni `%`), y de ahí salen
   `fold_expr` (texto, agregados) y `_plegado` (SQLAlchemy, listado, vía
   `literal_column`). El texto de `fold_expr` **no cambió ni un carácter** —es
   componente de la clave canónica y `v101` congela esa expresión—. Compilado,
   el listado emite ahora exactamente `fold_expr("licitaciones.<col>")`.
2. **Tecnología por solapamiento de arrays sobre una expresión única.**
   `tecnologia_tokens_sql(col)` =
   `string_to_array(replace(COALESCE(col, ''), ' ', ''), ',')`, y el filtro es
   `tokens && ARRAY[%s,…]::text[]` en los agregados, la rama FTS del listado,
   el export, la agenda, el RAG y el filtro de adjudicaciones (todos pasan por
   `tecnologia_en_csv_sql`, con los mismos parámetros que antes), y
   `tokens && CAST(ARRAY[%s, …] AS TEXT[])` en el listado de SQLAlchemy. La
   expresión de la columna es la misma cadena en todos.
   - Semántica conservada: código **entero** del CSV (`SAP` no trae `SAPHANA`),
     con mayúsculas distinguidas como antes, y con varios códigos basta uno.
   - Espacios: se quitan **todos** (era la regla del listado). La del agregado
     (`trim` de cada código) solo se distinguía en un código con un espacio
     *dentro*, y la ingesta escribe `",".join` de claves de
     `config.keywords.TECHNOLOGY_KEYWORDS`, ninguna con espacios.
   - Sin el índice sigue siendo secuencial, pero sin desplegar una lista por
     fila.
3. **Tests**: `tests/test_s1_paridad_filtros.py` —el fichero que los docstrings
   de los dos repositorios citaban y que no existía— compila el `WHERE` del
   listado y el de los agregados para un `q` y una tecnología y exige que la
   expresión de cada columna sea la misma cadena, sin parámetros ligados en la
   parte indexable, y que `fold_expr` conserve su texto. Su bloque con Postgres
   compara el recuento de los dos caminos en los casos que distinguen una
   semántica de otra (acentos, multi-tecnología, prefijo de otro código,
   espacios, mayúsculas, `NULL`).

## Paso 2 — migraciones propuestas

Dos revisiones y no una: la de tecnología es pequeña y se puede aplicar sola; la
de `q` es cara en disco y conviene decidirla después de medir.

Patrón de las dos, el de `v79`/`v101`/`v134`:

- `CREATE INDEX CONCURRENTLY IF NOT EXISTS` dentro de
  `op.get_context().autocommit_block()`.
- `SET statement_timeout = 0` y `SET lock_timeout = '30s'` como sentencias (el
  `options` de libpq no llega por el pooler; ver `v79._relax_timeouts`).
- La expresión **congelada** en una constante de la revisión, no importada de
  `db.sql_fragments` (ninguna migración de este linaje importa del árbol de la
  app), y un test que la compare con el fragmento vivo, como hace
  `tests/test_clave_canonica_index.py` con `v101`.
- `ANALYZE licitaciones` al final: sin él, el planificador no tiene
  estadísticas de la expresión indexada y estima a ciegas la selectividad del
  `LIKE` y del `&&` hasta que pase el autovacuum.
- **Un `CONCURRENTLY` que falla a medias deja un índice `INVALID`** y el
  `IF NOT EXISTS` del reintento lo da por bueno (la nota de `v134`). La
  revisión lo tira antes de crear si lo encuentra inválido
  (`_descartar_si_invalido` abajo), y el runbook comprueba
  `pg_index.indisvalid` después de aplicar.

### `v142_lic_tecnologia_tokens_gin`

```python
"""v142: GIN sobre los códigos de tecnología normalizados de ``licitaciones``.

Revision ID: v142_lic_tecnologia_tokens_gin
Revises: v141_tasas_anulacion_organo
"""

revision = "v142_lic_tecnologia_tokens_gin"
down_revision = "v141_tasas_anulacion_organo"

_INDICE = "idx_lic_tecnologia_tokens"

#: Gemela congelada de ``db.sql_fragments.tecnologia_tokens_sql("tecnologia")``.
_TOKENS_TECNOLOGIA_SQL = "string_to_array(replace(COALESCE(tecnologia, ''), ' ', ''), ',')"


def _descartar_si_invalido(nombre: str) -> None:
    fila = op.get_bind().exec_driver_sql(
        "SELECT i.indisvalid FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = %s",
        (nombre,),
    ).fetchone()
    if fila is not None and not fila[0]:
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {nombre}")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout = 0")
        op.execute("SET lock_timeout = '30s'")
        _descartar_si_invalido(_INDICE)
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDICE} "
            f"ON licitaciones USING gin (({_TOKENS_TECNOLOGIA_SQL}))"
        )
        op.execute("ANALYZE licitaciones")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '30s'")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDICE}")
```

- Opclass por defecto de GIN para arrays (`array_ops`): sirve `&&`, `@>`, `<@` y
  `=`. Todas las funciones de la expresión son `IMMUTABLE`, así que es
  indexable.
- **Tamaño: pequeño.** Una entrada por código distinto y fila, con las listas
  de filas comprimidas; la mayoría de filas llevan uno o dos códigos. Las
  ~1,46 M de PSCP sin etiqueta dejan `{}`, que GIN indexa con una sola entrada
  marcadora por fila (lo hace para que `<@` funcione), no con una por código.
- **Lo que gana**: cualquier consulta con filtro de tecnología pasa de escaneo
  secuencial a `Bitmap Index Scan` sobre las filas de esa tecnología. Abarata
  también las variantes por tecnología del snapshot del overview (ver abajo),
  que hoy se calculan secuenciales en cada pasada.
- **`idx_lic_tecnologia` (`v21`) no se retira aquí.** Lo siguen pudiendo usar
  las consultas de renovaciones (`db/repositories/renovaciones.py` y
  `services/competitive/renovaciones.py`), que filtran con
  `l.tecnologia IN (…)` **por igualdad** — y por eso se dejan fuera los
  expedientes multi-tecnología, el mismo defecto que el resto del producto
  corrigió al pasar a `tecnologia_en_csv_sql`. Cuando esas consultas se pasen
  al fragmento común, mirar el `idx_scan` del btree en `pg_stat_user_indexes`
  antes de decidir si sobra.

### `v143_lic_busqueda_plegada_trgm`

```python
"""v143: GIN trigram sobre las cuatro columnas plegadas de la búsqueda ``q``.

Revision ID: v143_lic_busqueda_plegada_trgm
Revises: v142_lic_tecnologia_tokens_gin
"""

revision = "v143_lic_busqueda_plegada_trgm"
down_revision = "v142_lic_tecnologia_tokens_gin"

_ORIGEN = "'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ'"
_DESTINO = "'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC'"

#: Gemelas congeladas de ``db.sql_fragments.fold_expr(<columna>)``. El orden es
#: el de ``_COLUMNAS_BUSQUEDA``: las cuatro tienen que existir para que el
#: ``OR`` se resuelva con ``BitmapOr``.
_INDICES_PLEGADOS = {
    "idx_lic_titulo_plegado_trgm": f"lower(translate(titulo, {_ORIGEN}, {_DESTINO}))",
    "idx_lic_descripcion_plegada_trgm": f"lower(translate(descripcion, {_ORIGEN}, {_DESTINO}))",
    "idx_lic_organo_plegado_trgm": f"lower(translate(organo_contratacion, {_ORIGEN}, {_DESTINO}))",
    "idx_lic_id_externo_plegado_trgm": f"lower(translate(id_externo, {_ORIGEN}, {_DESTINO}))",
}


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout = 0")
        op.execute("SET lock_timeout = '30s'")
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")  # ya la crea v50; por si acaso
        for nombre, expresion in _INDICES_PLEGADOS.items():
            _descartar_si_invalido(nombre)  # la misma función que en v142
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {nombre} "
                f"ON licitaciones USING gin (({expresion}) gin_trgm_ops)"
            )
        op.execute("ANALYZE licitaciones")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '30s'")
        for nombre in reversed(_INDICES_PLEGADOS):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {nombre}")
```

- **Las cuatro o ninguna.** Con una rama sin índice el `OR` vuelve a secuencial;
  crear tres sería pagar el disco sin ganar nada.
- `idx_licitaciones_titulo_trgm` (`v50`, sobre `titulo` sin plegar) **no** se
  retira aquí: lo puede seguir usando el `titulo ILIKE %s` de
  `LicitacionRepository.fetch_for_pdf`. Mirar su `idx_scan` antes de decidir.
- Un `q` de menos de tres caracteres no produce trigramas: ahí el planificador
  seguirá eligiendo el escaneo secuencial, que es lo correcto.
- El `LIKE %s ESCAPE '\'` de los agregados se reescribe como
  `expr ~~ like_escape($n, '\')`; sigue siendo indexable (el lado derecho no
  referencia la tabla y es inmutable).

### Riesgo principal: el tamaño de `descripcion`

`descripcion` es texto largo (en PLACSP, el `<summary>` del ATOM; en PSCP,
según conector). Un GIN trigram suele ocupar del orden de **una a tres veces**
el volumen del texto indexado, y ese volumen no se conoce desde esta máquina.
**Hay que medirlo antes de aplicar** `v143`:

```sql
SELECT pg_size_pretty(pg_relation_size('licitaciones'))         AS heap,
       pg_size_pretty(pg_total_relation_size('licitaciones'))   AS con_indices_y_toast,
       pg_size_pretty(pg_relation_size('idx_licitaciones_titulo_trgm')) AS trgm_titulo_v50;

SELECT count(*) FILTER (WHERE descripcion IS NOT NULL AND descripcion <> '') AS con_descripcion,
       round(avg(length(descripcion)))                                     AS media_descripcion,
       percentile_disc(0.99) WITHIN GROUP (ORDER BY length(descripcion))  AS p99_descripcion,
       pg_size_pretty(sum(octet_length(descripcion)))                      AS volumen_descripcion,
       pg_size_pretty(sum(octet_length(titulo)))                           AS volumen_titulo
FROM licitaciones;
```

El `idx_licitaciones_titulo_trgm` que ya existe es la calibración real: el
índice plegado de `titulo` ocupará casi lo mismo, y el de `descripcion`
aproximadamente eso multiplicado por `volumen_descripcion / volumen_titulo`.
Con el número delante, tres salidas si no cabe:

1. **Aceptarlo** si el disco de Supabase lo permite: es la única que conserva la
   semántica actual de `q` sin tocar código.
2. **Buscar `descripcion` por FTS** (`search_vector`, ya indexado desde `v50`) y
   el resto por trigram. Cambia la semántica de `q` sobre esa columna
   (palabras, no subcadenas) y exige mover a la vez listado y agregados —
   `tests/test_s1_paridad_filtros.py` lo vigila—.
3. **Sacar `descripcion` de `q`.** Es volver a la semántica anterior al
   2026-09-03 en los agregados; necesita decisión de producto.

Un índice parcial sobre «solo clasificadas» (`tecnologia IS NOT NULL AND
tecnologia <> ''`, el universo que el listado aplica siempre) reduciría mucho el
tamaño, pero **los agregados no aplican ese predicado**, así que no podrían
usarlo: solo aceleraría el listado.

Costes de escritura: un GIN con `fastupdate` acumula las inserciones en su lista
pendiente y la vacía al superar `gin_pending_list_limit` (4 MB por defecto) o en
el vacuum, así que algún lote del upsert puede pagar picos. Vigilar
`db_write_duration_seconds` y los eventos `write_slow` de `ops_events` durante
la primera semana. La construcción `CONCURRENTLY` hace dos pasadas por la tabla
por índice; con 972 MB de heap, reservar una ventana sin ingesta y, si el plan de
Supabase lo permite, subir `maintenance_work_mem` en la sesión de la migración.

## Cómo verificarlo con `EXPLAIN` después de aplicarlo

Primero, que los índices son válidos:

```sql
SELECT c.relname, i.indisvalid, pg_size_pretty(pg_relation_size(c.oid))
FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
WHERE c.relname IN ('idx_lic_tecnologia_tokens', 'idx_lic_titulo_plegado_trgm',
                    'idx_lic_descripcion_plegada_trgm', 'idx_lic_organo_plegado_trgm',
                    'idx_lic_id_externo_plegado_trgm');
```

Después, **con plan genérico**, que es el caso de psycopg tras preparar la
sentencia y el que motivó el paso 1:

```sql
SET plan_cache_mode = force_generic_plan;

PREPARE por_tecnologia(text) AS
  SELECT count(*) FROM licitaciones
  WHERE string_to_array(replace(COALESCE(tecnologia, ''), ' ', ''), ',') && ARRAY[$1]::text[];
EXPLAIN (ANALYZE, BUFFERS) EXECUTE por_tecnologia('SAP');
-- Esperado: Bitmap Index Scan on idx_lic_tecnologia_tokens, sin Seq Scan.

PREPARE por_q(text) AS
  SELECT count(*) FROM licitaciones
  WHERE lower(translate(titulo, 'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', 'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')) LIKE $1
     OR lower(translate(descripcion, 'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', 'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')) LIKE $1
     OR lower(translate(organo_contratacion, 'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', 'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')) LIKE $1
     OR lower(translate(id_externo, 'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', 'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')) LIKE $1;
EXPLAIN (ANALYZE, BUFFERS) EXECUTE por_q('%murcia%');
-- Esperado: BitmapOr de cuatro Bitmap Index Scan (uno por idx_lic_*_plegad*_trgm).

-- Contraprueba del paso 1: con los parámetros en el translate, el mismo índice NO se usa.
PREPARE por_q_ligado(text, text, text) AS
  SELECT count(*) FROM licitaciones WHERE lower(translate(titulo, $2, $3)) LIKE $1;
EXPLAIN EXECUTE por_q_ligado('%murcia%',
  'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', 'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC');
-- Esperado: Seq Scan.

RESET plan_cache_mode;
DEALLOCATE ALL;
```

Y en la API, con la consulta real: `EXPLAIN` del `WHERE` que emite
`build_licitaciones_where(LicitacionesFilters(q="murcia"))` y del que emite
`_base_filters(q="murcia")` (los dos se obtienen compilando, como hacen los
tests de `tests/test_s1_paridad_filtros.py`). Por último,
`pg_stat_user_indexes.idx_scan` de los cinco índices tras un día de tráfico.

**Tests que acompañan a las migraciones** (patrón de
`tests/test_clave_canonica_index.py`): cargar cada revisión por ruta y exigir
`_TOKENS_TECNOLOGIA_SQL == tecnologia_tokens_sql("tecnologia")` y
`_INDICES_PLEGADOS[...] == fold_expr(<columna>)` para las cuatro columnas. Si un
fragmento cambia, el test obliga a escribir una revisión nueva que reconstruya
el índice en vez de dejarlo muerto en silencio.

## Snapshots del overview por filtro: qué se hizo sin esquema y qué no

**Hecho, sin migración.** `kpi_snapshots.dimension` es texto libre y la tabla no
tiene unicidad por métrica, así que una variante es una fila más con
`dimension = 'tecnologia:<código>'`:

- El precálculo (`db/repositories/kpi_snapshots.py::compute_overview_snapshot_rows`,
  llamado desde `db/kpi_precompute.py::compute_all_kpis`) añade `ov_kpis` y
  `ov_tasa_anulacion` para las **cinco** tecnologías más frecuentes del corpus
  (`AggregateRepository.tecnologias_mas_frecuentes`), con las mismas llamadas al
  repositorio que el camino en vivo. Cada variante va en su propio `SAVEPOINT`:
  si una falla, se pierde ella sola y no el snapshot global.
- `read_overview_snapshot_for` sirve la variante cuando el filtro es
  **exactamente** una de esas tecnologías; con cualquier otro filtro, `None`
  como antes. En la variante `importe_p75` y `total_activas` van a `None`, así
  que `/analytics/resumen/hoy` responde igual que antes con ese filtro.
- Los indicadores de adjudicaciones (`ov_adj_indicadores`), que nunca
  dependieron del filtro, se leen de la fila global **con cualquier filtro**
  (`read_adj_indicadores_snapshot`). Era la pieza más cara (42 s medidos) y se
  recalculaba en cada búsqueda.

**Por qué en `kpi_precompute` y no en `scheduler/aggregates_precompute.py`.**
`persist_snapshots` hace `DELETE FROM kpi_snapshots` antes de insertar el
snapshot de la pasada, y `aggregates_precompute` corre **después** en
`CANONICAL_STEPS`. Escritas desde allí, las variantes (a) desaparecerían en el
`DELETE` de cada pasada siguiente, y (b) llevarían un `computed_at` posterior al
del snapshot global: `db.kpi_precompute.get_all_latest` —que lee solo las filas
de `MAX(computed_at)`— devolvería únicamente las variantes, y el
`last_pipeline_run` de `scheduler/healthcheck.py` avanzaría aunque
`kpi_precompute` hubiese fallado.

**Coste**: dos agregaciones por tecnología y pasada, más una para elegirlas.
Hasta que exista `v142` son escaneos secuenciales (el paso de las pasadas corre
con `statement_timeout` de 300 s, perfil `scraper`); con `v142` pasan a leer
solo las filas de cada tecnología.

**Lo que sí exigiría esquema, y no se hace:**

- Variantes para combinaciones arbitrarias de filtros (tecnología + CCAA, `q`…):
  necesitarían una clave de filtro normalizada (hash de los filtros ya
  canonizados) y probablemente una tabla propia con su ciclo de vida. En
  `kpi_snapshots` quedarían atadas al borrado total de cada pasada y al
  `DISTINCT ON (metrica)` por `dimension` de la lectura.
- Unicidad `(metrica, dimension)` —hoy el `DISTINCT ON` de la lectura suple su
  falta—, que haría falta para escribir variantes con un `UPSERT` en otro paso
  y otra cadencia sin chocar con el reemplazo total.
- Variantes con `importe_p75`/`total_activas` por filtro: `overview_para_hoy`
  calcula el P75 del subconjunto dentro de la misma consulta, así que
  precalcularlo por filtro solo ahorraría esa consulta si además se
  precalculasen las otras tres ventanas, que dependen de la hora de la petición.
  No compensa.
