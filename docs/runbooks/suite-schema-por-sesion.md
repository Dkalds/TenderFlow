# Suite de integración: schema por sesión (`TF_TEST_SCHEMA_STRATEGY=truncate`)

Estado a 2026-11-19: **el default es `truncate`** —un schema por
sesión/worker vaciado entre tests—. `TF_TEST_SCHEMA_STRATEGY=schema` (un
schema Postgres nuevo por test, `tests/conftest.py::_pg_schema_por_creacion`)
queda como vuelta atrás. Los pasos de abajo se recorrieron el 2026-11-18/19;
lo que se midió está en «Cómo se cambió el default».

### Medido el 2026-11-06 (4 CPU, cluster cargado por otras suites)

Coste por test de dejar la base limpia, en una base con el DDL de head
(107 tablas), media de 10-15 iteraciones:

| Mecanismo | ms/test |
| --- | --- |
| Schema nuevo + DDL + `DROP SCHEMA` (default `schema`) | 1200-1500 |
| `CREATE DATABASE … TEMPLATE` + `DROP DATABASE` | 970-4200 |
| `TRUNCATE` de todas las tablas | 970-1150 |
| `DELETE` de todas las tablas sin triggers | ≈90 |
| Huella de catálogo (comprobación de deriva) | ≈110 |

`CREATE DATABASE … TEMPLATE` por test no gana: copia la base entera y
`DROP DATABASE` espera a un checkpoint inmediato de todo el cluster (más de
diez minutos con el disco ocupado por otras sesiones). `TRUNCATE` tampoco:
crea ficheros nuevos para cada tabla e índice. Por eso `truncate` vacía con
`DELETE` (y con `TRUNCATE` sólo si el rol no puede fijar
`session_replication_role`). La suite tiene unos 3.300 tests de integración:
a ≈1,2 s de DDL cada uno frente a ≈0,2 s de vaciado más huella, la estrategia
`truncate` ahorra del orden de 3.000 s de trabajo de BD en serie.

## Qué garantiza hoy `truncate`

Detalle en el comentario de `ESTRATEGIA_SCHEMA` en `tests/conftest.py`:

- Datos vaciados: `DELETE` de todas las tablas con
  `session_replication_role = replica` (sin FKs ni triggers), cada uno en su
  transacción y todos en un pipeline; `TRUNCATE … CASCADE` si el rol no tiene
  ese permiso.
- Semillas de migración restauradas (sin columnas generadas, con
  `OVERRIDING SYSTEM VALUE`).
- **Secuencias devueltas al estado de recién migrado** (no a 1), incluidas las
  que no son de ninguna tabla.
- Vistas materializadas refrescadas.
- **Deriva de DDL detectada por huella de catálogo** (columnas, restricciones,
  índices, triggers, funciones, vistas, políticas RLS, RLS activado y
  permisos); el schema se reconstruye y el test culpable falla con nombre.
- **Un schema a medio construir se rehace** en el siguiente test: se construye
  perezosamente y, si el vaciado falla, se reconstruye. Antes un fallo al
  reconstruir (p. ej. sin locks libres) dejaba en error al resto del worker.
- `@pytest.mark.schema_propio` para los tests que alteran el DDL a propósito;
  los que ya lo llevan salen de `grep -rn schema_propio tests/` (una lista a
  mano aquí se quedaba atrás). Puede faltar alguno que altere el DDL por una
  vía indirecta (un repositorio que cree tablas): la huella lo detectará en
  la primera tirada.
- Un valor desconocido de `TF_TEST_SCHEMA_STRATEGY` es un error de uso, no un
  retorno silencioso a `schema`.

## Pasos para cambiar el default

1. Tirada completa con la estrategia nueva, en CI o en local con Postgres:

   ```bash
   TF_TEST_SCHEMA_STRATEGY=truncate make test-integration
   ```

   Criterio: verde, incluido `tests/test_aislamiento_entre_tests.py`, y **cero**
   errores «el test alteró el DDL del schema compartido». Cada uno de esos es
   un test que hay que marcar `schema_propio` (o reescribir para no tocar DDL).
2. Repetir con orden aleatorio y con xdist (`make test-parallel` con la
   variable puesta): las fugas por orden sólo aparecen así.
3. Medir: duración de `make test-integration` con `schema` y con `truncate`
   en el mismo runner. Si la mejora no compensa, no se cambia.
4. Sólo entonces cambiar el default en `ESTRATEGIA_SCHEMA` y dejar `schema`
   como vuelta atrás por variable.

## Cómo se cambió el default (2026-11-18/19)

Local, 4 CPU, Postgres 16, `-n auto`, `(unit or integration) and not slow`:

- Paso 1: la primera tirada con `truncate` dio 7 errores de DDL compartido y
  un test que necesitaba la tabla recién creada (`reltuples = -1`); los ocho
  llevan ahora `schema_propio`. La siguiente tirada, en verde.
- Paso 2: con xdist y orden barajado (semilla fija, un plugin desechable que
  baraja en `pytest_collection_modifyitems`) fallan unos 40 tests **con las dos
  estrategias**: 44 con `schema` y 38 con `truncate` en la misma semilla, de los
  mismos ficheros. Es estado de módulo que se filtra entre tests (p. ej. un test
  que sustituye `config.settings` y otro que parchea el objeto viejo), no datos
  de la BD. Arreglado el 2026-11-20: eran cuatro fugas (un test que vaciaba
  `config*` de `sys.modules`, un mock del repositorio de señales ligado en el
  primer import de `services.tech_signal`, las recargas de `db.users` y la
  organización del presupuesto LLM que quedaba puesta en el worker). La suite
  pasa barajada con las semillas 4242 y 1337 y con las dos estrategias.
- Paso 3: 1.618 s con `schema` frente a 508 s con `truncate`. En CI, el job `Tests (Postgres)` pasó de 26 min 15 s (#758, `schema`) a 14 min 46 s (#761, `truncate`).

## Riesgos conocidos que no cubre

- Semillas con claves foráneas entre sí: se restauran por orden alfabético
  de tabla; una semilla que referencie a otra tabla sembrada que va después
  fallaría. No hay ningún caso hoy (sólo `api_key_tiers`), pero una migración
  futura podría crearlo.
- Datos escritos en `public` con nombre cualificado: el vaciado sólo
  alcanza al schema de la sesión.

Resuelto el 2026-11-18 (#758): re-materializar el DDL sobre una base ya usada
fallaba porque se migraba la propia base de tests. `_materialize_schema_ddl`
migra ahora en una base hermana `<base>_ddl` que no se borra (`DROP DATABASE`
espera a un checkpoint), con un advisory lock entre sesiones; el rol de
`TEST_DATABASE_URL` necesita `CREATEDB` la primera vez.
