# Suite de integración: schema por sesión (`TF_TEST_SCHEMA_STRATEGY=truncate`)

Estado a 2026-09-19: **el default sigue siendo `schema`** (un schema Postgres
nuevo por test, `tests/conftest.py::_pg_schema_por_creacion`). La estrategia
`truncate` —un schema por sesión/worker y `TRUNCATE … RESTART IDENTITY
CASCADE` entre tests— está escrita y endurecida, pero **no se ha ejecutado
nunca contra Postgres** desde la máquina que la escribió. Este runbook dice qué
falta para cambiar el default y cómo hacerlo sin romper el aislamiento.

## Qué garantiza hoy `truncate`

Detalle en el comentario de `ESTRATEGIA_SCHEMA` en `tests/conftest.py`:

- Datos vaciados (`TRUNCATE` de todas las tablas del schema).
- Semillas de migración restauradas (sin columnas generadas, con
  `OVERRIDING SYSTEM VALUE`).
- **Secuencias devueltas al estado de recién migrado** (no a 1), incluidas las
  que no son de ninguna tabla.
- Vistas materializadas refrescadas.
- **Deriva de DDL detectada por huella de catálogo** (columnas, restricciones,
  índices, triggers, funciones, vistas); el schema se reconstruye y el test
  culpable falla con nombre.
- `@pytest.mark.schema_propio` para los tests que alteran el DDL a propósito;
  ya marcados: `test_analytics_quality.py` (módulo), `test_nucleo_tipado_pg.py`
  (módulo), los tres `*_float4` de `test_db_upsert.py`,
  `test_healthcheck_ops_events_tabla_ausente` y
  `test_list_deliveries_degrada_a_vacio_si_la_consulta_falla`. La lista sale
  de un `grep` de DDL en tests con BD; puede faltar alguno que altere el DDL
  por una vía indirecta (un repositorio que cree tablas): la huella lo
  detectará en la primera tirada.
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

## Riesgos conocidos que no cubre

- Semillas con claves foráneas entre sí: se restauran por orden alfabético
  de tabla; una semilla que referencie a otra tabla sembrada que va después
  fallaría. No hay ningún caso hoy (sólo `api_key_tiers`), pero una migración
  futura podría crearlo.
- Datos escritos en `public` con nombre cualificado: el `TRUNCATE` sólo
  alcanza al schema de la sesión.
