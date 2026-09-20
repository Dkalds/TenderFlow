---
tags: [runbook, operacion, migracion]
---

# Runbook — ventana del núcleo tipado (T2: columnas sombra de `licitaciones`)

**Qué hace este runbook:** lleva a producción las columnas sombra tipadas de
`licitaciones` (T2 del [plan de arquitectura v2](../plans/2026-09-plan-arquitectura-v2.md)
§6, y el P2 «Migrar `licitaciones.importe` de `real` a `double precision`» del
[backlog](../IMPROVEMENT_BACKLOG.md)) sin reescribir la tabla ni tomar un lock
exclusivo largo.

| Columna vieja | Sombra | Tipo |
|---|---|---|
| `fecha_publicacion` (`text`) | `fecha_publicacion_ts` | `timestamptz` |
| `fecha_limite` (`text`) | `fecha_limite_ts` | `timestamptz` |
| `importe` (`real` en prod) | `importe_num` | `numeric(14,2)` |
| `duracion_valor` (`real` en prod) | `duracion_valor_num` | `numeric` |

**Quién lo ejecuta:** una persona, con acceso de escritura a la BD de
producción. Los pasos 1, 4 y 6 son decisiones con el dato real delante.

**Estado al escribir esto (2026-09-18):** no ejecutado. En el repo existen
`v133_nucleo_tipado_sombra` (columnas + función de conversión),
`v134_nucleo_tipado_indices` (índices `CONCURRENTLY`), la escritura dual en
`db/upsert.py`, el backfill (`scripts/backfill_nucleo_tipado.py`) y los
fragmentos de lectura dual detrás de `NUCLEO_TIPADO_LECTURA` (apagado).

---

## Por qué así y no con un `ALTER COLUMN ... TYPE`

`ALTER TABLE licitaciones ALTER COLUMN importe TYPE double precision`
reescribe la tabla entera (~1,3 M filas) con `ACCESS EXCLUSIVE` y reconstruye
`idx_lic_importe`. El precedente es `v68`: una columna generada que tardó más
de 30 min con la tabla bloqueada y no cupo en la ventana. Con columnas sombra
cada paso es corto o no bloquea:

- `v133` es un `ADD COLUMN` nullable sin default: sólo catálogo, un instante de
  lock, y con `lock_timeout = 5s` para que no se quede encolado detrás de una
  consulta larga bloqueando a todos los demás.
- El backfill va por lotes de clave primaria, una transacción por lote, con
  `lock_timeout` de 2 s: si choca con la ingesta, cede y reintenta.
- `v134` usa `CREATE INDEX CONCURRENTLY`: no bloquea escrituras.

## Lo que el backfill **no** arregla

El `real` de producción ya perdió precisión: de un importe de 12.345.678,91 €
sólo guarda 12.345.679. El backfill traduce **lo que hay** (pasando por
`double precision`, que es lo máximo que se puede rescatar); el importe exacto
sólo llega con la **siguiente reingesta** de ese expediente, porque la escritura
dual traduce el `float` del conector antes de que toque la columna vieja. Por
eso la verificación compara las sombras numéricas con tolerancia relativa
`1e-5` —la misma cota que `FLOAT_REL_TOL`— y un segundo pase del backfill **no**
machaca un `importe_num` exacto con el valor degradado del `real`.

---

## Prerrequisitos

1. Producción al día hasta la revisión anterior a `v133` (`alembic history`
   la dice: al integrar ramas el `down_revision` de `v133` puede no ser
   `v132_informes_programados`, que es el que aparece en los comandos de
   abajo). La CLI de Alembic contra Supabase necesita `PGSSLROOTCERT`.
2. Ventana valle: ni el ATOM ni un backfill de conector corriendo. El backfill
   convive con la ingesta, pero la ventana más corta es la que no compite.
3. Una copia reciente (`docs/runbooks/backup-restore.md`).
4. **No** correr `scripts/fix_dates_adjudicaciones.py` durante la ventana:
   actualiza fechas de `licitaciones` sin pasar por el upsert. Si se corre
   después, volver a pasar el paso 3.

## Paso 1 — plan antes de apply

```bash
alembic upgrade v132_informes_programados:v133_nucleo_tipado_sombra --sql
```

Revisar que el SQL es exactamente: `CREATE OR REPLACE FUNCTION
nucleo_iso_a_timestamptz`, `SET LOCAL lock_timeout`, un único `ALTER TABLE
licitaciones ADD COLUMN IF NOT EXISTS ...` con las cuatro columnas **sin
`DEFAULT`**, y `RESET lock_timeout`. Si aparece un `DEFAULT` o un `USING`, parar:
eso sí reescribe la tabla.

## Paso 2 — migración de columnas y despliegue

```bash
alembic upgrade v133_nucleo_tipado_sombra
```

**No** `upgrade head`: `v134` va después del backfill (paso 5). Si falla por
`lock_timeout`, hay una consulta larga sobre `licitaciones`; esperar y
reintentar, no subir el timeout.

Desplegar a continuación el código de esta rama (API, worker y el plano que
ingiera). La escritura dual se activa sola: `db/upsert.py` comprueba en el
catálogo, en cada chunk de 500 filas, que las cuatro columnas existen y, si
existen, las escribe. Un proceso que arrancó antes de la migración empieza a
escribirlas en su siguiente chunk, sin reinicio. (Desplegar el código **antes**
de la migración también es seguro: sin columnas, el upsert es el de siempre.)

Comprobación rápida tras la primera ingesta:

```sql
SELECT count(*) FILTER (WHERE importe_num IS NOT NULL) AS con_sombra,
       count(*) AS total
FROM licitaciones
WHERE fecha_extraccion >= to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD');
```

## Paso 3 — backfill por lotes

```bash
python -m scripts.backfill_nucleo_tipado --verificar      # línea base: todo divergente
python -m scripts.backfill_nucleo_tipado --lote 5000 --pausa 0.1
```

Cada lote imprime su última `id_externo`; si la ventana se corta, se reanuda
con `--desde '<esa clave>'`. Salida 2 = un lote agotó cinco reintentos por
locks: mirar qué retiene `licitaciones` (`pg_stat_activity`) antes de seguir.

Referencia de coste: la función de fechas usa un bloque `EXCEPTION` de
PL/pgSQL (una subtransacción por llamada), así que el cuello de botella es CPU,
no I/O. Medir el primer lote y extrapolar antes de comprometer la ventana.

## Paso 4 — verificación (criterio de parada)

```bash
python -m scripts.backfill_nucleo_tipado --verificar
```

| Contador | Esperado | Si no |
|---|---|---|
| `divergentes` (total y por sombra) | **0** | Volver al paso 3. Si persiste, hay un escritor fuera del upsert tocando esas columnas: encontrarlo antes de seguir. |
| `fecha_publicacion_no_iso`, `fecha_limite_no_iso` | anotar | No son divergencia: la sombra dice bien que no hay fecha. Son las filas que impedirían retirar la columna de texto sin perder nada, y el numerador del criterio «cero fechas no ISO» del plan. |
| `importe_sin_sombra` | anotar | Importes que no caben en `numeric(14,2)` (≥ 1e12) o `NaN`: errores de parseo. Revisarlos a mano. |
| `periodo_distinto` | **0** para poder mover la clave | Filas cuyo año-mes en UTC no coincide con el prefijo del texto (offset ≠ UTC que cruza medianoche a fin de mes). La clave canónica **sigue leyendo el texto** en cualquier caso; este número sólo decide si algún día puede dejar de hacerlo. |

Anotar los cuatro números y la fecha en el ítem T2 del plan.

## Paso 5 — índices

```bash
alembic upgrade v134_nucleo_tipado_indices
```

Y comprobar que no quedó ninguno a medias (un `CONCURRENTLY` que falla deja un
índice `INVALID` que un reintento con `IF NOT EXISTS` daría por bueno):

```sql
SELECT c.relname, i.indisvalid
FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
WHERE c.relname IN ('idx_lic_fecha_publicacion_ts', 'idx_lic_fecha_limite_ts');
```

Si alguno sale `false`: `DROP INDEX CONCURRENTLY <nombre>;` y repetir el paso.

## Paso 6 — lecturas (fuera de esta ventana)

`NUCLEO_TIPADO_LECTURA=true` cambia lo que devuelven `columna_nucleo`,
`columna_nucleo_sql`, `importe_sql`, `importe_select_sql` y `fecha_valida_sql`
(`db/sql_fragments.py`). Desde 2026-09-19 las cinco consultas calientes del
criterio de `EXPLAIN` del plan los consumen, así que **encender el flag las
mueve a las cinco a la vez**:

| Consulta | Dónde | Qué pasa a la sombra |
|---|---|---|
| Listado | `LicitacionRepository.list_paginated` (+ rama FTS `_list_fts`) | filtros de publicación, cierre, plazo e importe; `ORDER BY`; importe proyectado |
| Cursor | `LicitacionRepository.list_cursor` | los mismos filtros; clave del cursor y su orden; importe proyectado |
| Scoring | `AggregateRepository.scoring_candidates`, `licitaciones_by_ids`, `importe_percentiles_universo` | plazo vivo y su guarda; filtros; importe proyectado y percentiles |
| Overview | `AggregateRepository.overview_kpis` | filtros; `SUM`/`AVG` de importe |
| Pública | `PublicoRepository.ficha` y `listar` | sólo el importe proyectado (sustancia y orden son la definición de la vista materializada y no se mueven) |

El resto de agregados que comparten `build_licitaciones_where` **no** se mueve:
el constructor sólo lee la sombra con `nucleo=True`, y sólo lo pasan esas
consultas. Con el flag apagado el SQL de las cinco es byte a byte el anterior
(comprobado al migrarlas comparando el SQL y los parámetros emitidos contra el
commit anterior; lo sostienen `tests/test_nucleo_tipado_consultas.py`).

Antes de encenderlo en producción, y sólo después de un paso 4 con cero
divergencias:

1. `EXPLAIN` de las cinco con el flag en `false` y en `true` (una sesión con
   `SET` no basta: el flag es un setting de la app; usá un entorno de staging o
   el SQL que emiten los tests). Criterio del plan: ningún cast en tiempo de
   ejecución sobre esas columnas en el `WHERE`/`ORDER BY`.
2. Comparar resultados de cada una con los dos valores del flag sobre la misma
   BD (mismos ids, mismo orden, mismos totales).
3. Comprobar la zona horaria de la sesión (`SHOW timezone` → `UTC`): los
   parámetros de fecha (`'2026-01-31'`) se interpretan como `timestamptz` en esa
   zona. Ver el docstring de `columna_nucleo_sql`.

**La clave canónica no se mueve** en ningún caso: `periodo_publicacion_sql`
sigue leyendo el texto (índice `v92`, vistas `v101`/`v102`, sitemap). Lo fija
`tests/test_nucleo_tipado.py`.

## Lo que queda después (no es de esta ventana)

- **`FLOAT_REL_TOL`**: se baja al ruido de float8 (o se retira del campo) **sólo
  después** de que las lecturas de `importe` salgan de `importe_num` y se haya
  verificado en producción; nunca en el mismo cambio que la migración (backlog).
- Limpieza de las filas basura de `licitaciones_history` con
  `changed_fields='importe'` y de sus `contrato_eventos` de tipo
  `modificacion` (criterio del P2 del backlog).
- Retirar las columnas viejas y renombrar: otra revisión, otra ventana, con
  RFC si cambia el contrato de la API.

## Vuelta atrás

- Antes del paso 6: `alembic downgrade v133_nucleo_tipado_sombra` (quita los
  índices) y, si hace falta, `alembic downgrade v132_informes_programados`
  (quita columnas y función; `DROP COLUMN` es sólo catálogo). El upsert
  pregunta al catálogo en cada chunk, así que deja de escribir las sombras en
  el siguiente chunk sin reiniciar nada. Un chunk que estuviera en vuelo justo
  durante el `DROP` falla y lo reintenta `run_connector`.
- Después del paso 6: `NUCLEO_TIPADO_LECTURA=false` devuelve cada fragmento a
  la columna vieja byte a byte, sin despliegue.
