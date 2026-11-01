# Testing

Guía para ejecutar, escribir y entender los tests del proyecto.

## Auto-marking por convención de nombre + uso de fixtures

`tests/conftest.py` asigna markers automáticamente. **No marcar tests manualmente.**

| Regla                                                  | Marker        |
|--------------------------------------------------------|---------------|
| `_e2e`, `visual_regression` en el nombre               | `e2e`         |
| `performance`, `load` como **palabra** de la ruta      | `load`        |
| `property`, `properties`, `property_based`             | `property`    |
| `integration_e2e` (o `/integration/` en el path)       | `integration` |
| Cierre de fixtures incluye `tmp_db`/`api_db` (BD real) | `integration` |
| Todo lo demás                                          | `unit` (default) |

Prioridad de evaluación: e2e > load > property > integration (nombre) >
integration (fixture PG) > unit.

Los tokens de ruta se buscan en la ruta del módulo **relativa a la raíz del
repo** (`tests/test_performance.py`), no en la absoluta: los directorios padre
del checkout —un worktree `…-performance-…`, `~/Downloads`— no cambian la
categoría de nada.

`load` y `performance` casan como palabra, no como subcadena: `load` vive
dentro de «download», y `test_bulk_downloader.py` y
`test_exports_download_session.py` estuvieron fuera de `make check` por eso
hasta 2026-10. Qué módulos quedan `load` lo fija por nombre
`tests/test_markers_automarking.py`: si añadís uno de carga de verdad, se
declara ahí; si ese test falla con un módulo funcional, renombralo.

### Un test `unit` no sale a la red

Un fixture autouse (`_sin_red_en_tests_unitarios`) hace **fallar** al test
`unit` que resuelve un nombre o conecta fuera de la máquina. Falla con
`pytest.fail`, que atraviesa los `except Exception` del código bajo prueba, y
también si el código se traga el corte (un hilo, `except BaseException`). El
loopback y los literales de IP pasan. Si el test necesita una respuesta DNS,
parcheá `socket.getaddrinfo` (ver `dns_publico` en `tests/test_ssrf.py`); si
lo que falta es un mock, el fallo dice qué host se intentó alcanzar.

La regla por fixture (2026-08) hace la taxonomía **real**: un test que abre un
schema Postgres — directamente (`tmp_db`, `api_db`) o transitivamente
(`client`, `api_key`, `auth`…, que declaran `api_db` en su cierre) — queda
`integration` sea cual sea el nombre del fichero, y `unit` vuelve a significar
"sin I/O externo". `make check` ejecuta `unit or integration` (misma cobertura
que antes del cambio); `make test-unit` es el bucle rápido sin BD.

Si necesitás que un test tenga otro marker de NOMBRE, **renombrá el archivo o
la función** — no uses `@pytest.mark.xxx`.

## Fixtures disponibles

| Fixture   | Depende de     | Descripción                                                      |
|-----------|----------------|------------------------------------------------------------------|
| `tmp_db`  | `_pg_schema`   | Schema Postgres aislado por test (DDL completo + seeds de migración replicados; ver `conftest.py::_pg_schema_ddl`). Requiere `TEST_DATABASE_URL`. Devuelve `(db_mod, None)` — el segundo elemento era el path SQLite y sobrevive por compatibilidad de firma. |
| `api_db`  | `_pg_schema`   | Mismo schema aislado, orientado a tests de API (inicializa `db_mod`). |
| `api_key` | `api_db`       | Crea una API Key de test y devuelve el token en bruto (string).  |
| `client`  | `api_db`       | `TestClient` de FastAPI con BD temporal (`raise_server_exceptions=True`). |
| `auth`    | `api_key`      | Dict con headers de autenticación: `{"X-API-Key": "<token>"}`.   |

## Cómo agregar un test

1. Elegí el nombre del archivo/función con el token adecuado (ver tabla arriba).
2. Ubicá el archivo en `tests/`.
3. Usá los fixtures existentes — no creés tu propia BD de test.
4. **Nunca** uses `@pytest.mark.unit`, `@pytest.mark.e2e`, etc. El auto-marking se encarga.

Ejemplo:

```python
# tests/test_parser_properties.py → marcado automáticamente como "property"
def test_parser_properties_handles_empty(tmp_db):
    db_mod, path = tmp_db
    ...
```

## Tests de escenario y casos de uso

[casos-de-uso.md](casos-de-uso.md) lista lo que una persona tiene que poder
hacer con el producto. Cada caso necesita un **recorrido** que lo cite por su
identificador (`CU-NN`), y `make check-casos-uso` falla si a alguno le falta.

Un test de escenario (`tests/test_escenario_*.py`) recorre un caso de punta a
punta por la API. Se diferencia de un test de ruta en tres cosas:

- **La sesión es de verdad.** `tests/escenarios.py::abrir_sesion` da de alta,
  inicia sesión y manda el CSRF de la cookie en cada escritura. Nada de
  `dependency_overrides` de autenticación: un escenario que se salta la sesión
  no prueba el camino que recorre el navegador.
- **Cada persona, su cliente.** Las cookies viven en el `TestClient`; dos
  usuarios en el mismo escenario son dos llamadas a `abrir_sesion`.
- **Lo único que se siembra a mano son los expedientes**
  (`sembrar_licitacion`): los trae la ingesta, no el usuario. Todo lo demás se
  crea por la API, que es lo que se está probando.

Un escenario afirma lo que el usuario ve al final de cada paso, y también lo
que **no** puede hacer (el 403 de quien solo lee, el 409 de una transición que
no existe). Los detalles de cada contrato siguen en los tests de su ruta.

El mismo caso en el navegador es un E2E de Playwright (`web/e2e/`). Los specs
que escriben usan una cuenta desechable (`web/e2e/cuenta-desechable.ts`), no la
del seed: comparten base con las capturas de `visual.spec.ts`.

## Máquinas de estado (Hypothesis)

Donde el fallo está en la **secuencia** y no en un paso, el test es una
`RuleBasedStateMachine`: Hypothesis encadena operaciones al azar y los
invariantes se comprueban tras cada una.

| Test | Qué encadena | Contra qué se compara |
|------|--------------|-----------------------|
| `test_pursuit_maquina_property.py` | Parches arbitrarios de una oportunidad, `null` incluido | Invariantes del embudo escritos sin leer la tabla de transiciones del servicio |
| `test_watchlist_rules_maquina_property.py` | Altas, ediciones y borrados de reglas de dos personas | Un modelo en memoria, y un oráculo en Python de qué expedientes casan |

Dos reglas al escribir una:

- **El oráculo no comparte código con lo que prueba.** Si los invariantes
  reutilizan la tabla o el predicado del servicio, un error ahí pasa el test.
- **Acotá los ejemplos** (`max_examples`, `stateful_step_count`): con base de
  datos, cada paso son varias consultas.

Cuando una máquina falla, Hypothesis imprime la secuencia mínima que lo
reproduce; ese es el caso que hay que convertir en test de regresión con nombre
(los tres primeros fallos que encontraron están en
`tests/test_escenario_oportunidad.py` y en el corpus de la máquina de reglas).

## Frontend: propiedades y mutación

**Tests de propiedades (fast-check).** Los ficheros `*.property.test.ts`
conviven con los tests de ejemplo y corren en `npm run test`. Dicen lo que un
ejemplo no puede: ida y vuelta, idempotencia e invariantes. Usan `comprobar()`
de `web/src/test/propiedades.ts`: semilla fija (lo que pasa en local pasa en CI)
y 200 casos por propiedad. Para explorar con otra semilla:
`FC_SEED=azar FC_NUM_RUNS=20000 npm run test -- --expect-min=1 <fichero>`. Un
contraejemplo que destape un fallo se queda en el test con nombre; si el fallo
no se arregla en el mismo cambio, como `it.fails` con el porqué.

**Mutation testing (Stryker).** `make web-mutation` (o `cd web && npm run
test:mutation`) muta una muestra pequeña de `web/src/lib` y vuelve a correr los
tests de `src/lib` que cubren cada mutante; `FILES="src/lib/x.ts"` elige otros
ficheros. Es un informe, no un gate, igual que `make mutation-sample` en el
backend: un superviviente puede ser un test que falta o una mutación
equivalente. El informe queda en `web/reports/mutation/`. Usa el runner
`vitest-5` de `web/scripts/stryker-vitest-5.mjs` porque el oficial no
selecciona tests con vitest 5 —todos los mutantes «sobreviven» sin dar error—;
su cabecera dice cuándo retirarlo, y una guarda falla si un mutante se queda sin
tests que correr.

## Ejecutar tests por categoría

```bash
make check             # lint + typecheck + unit e integration (gate local)
make test-unit         # unit (sin slow, sin BD) — bucle rápido de desarrollo
make test              # suite completa excepto integration_e2e
make test-parallel     # ídem con pytest-xdist -n auto (opt-in, ver Makefile)
make test-all          # TODOS los tests
make test-integration  # solo integration (requiere TEST_DATABASE_URL)
make test-e2e          # solo e2e
make test-property     # solo property
make test-load         # solo load
make test-perf         # test_performance.py (marker slow)
```

## Skips condicionales

Algunos tests se saltan **a propósito** según el entorno. No son deuda: cada
`pytest.skip` lleva un motivo explícito. Política:

| Test | Condición de skip | Por qué es correcto |
|------|-------------------|---------------------|
| `test_document_fetcher_formatos.py` | `ocrmypdf` no está en el `PATH` (`skipif`) | El OCR es un binario del sistema, no un paquete de Python: ni `requirements-dev.txt` ni CI lo instalan, así que ese caso solo corre donde alguien lo haya instalado a mano. |

Los `pytest.importorskip` de `yaml`, `sklearn`, `pandas`, `numpy` y `openai` protegen
dependencias que `requirements-dev.txt` **sí** instala: en CI no se disparan. Si
alguno se disparara, el entorno estaría roto, no "mínimo".

(Los archivos `test_unit_coverage_batch1b.py` y `test_visual_regression.py`
que esta tabla citaba se redistribuyeron/retiraron — las filas se eliminaron
en 2026-08 al detectar que documentaban tests inexistentes. En 2026-09 salió
`test_shared_schemas.py` junto con el módulo que probaba, y dejaron de saltarse
`test_dedupe_quality.py`, `test_placsp_connector_parity.py` y
`test_aislamiento_entre_tests.py`: sus condiciones de skip ocultaban regresiones
en vez de describir un entorno, y ahora fallan con mensaje.)

Regla general: usar `pytest.importorskip("dep")` para dependencias opcionales y
`pytest.skip(motivo)` con un mensaje claro para condiciones de entorno. CI instala
`requirements-dev.txt` y el extra `[pliegos]`; lo que quede fuera se salta también
allí. Un skip no debe depender de un dato que el propio test debería garantizar
(un fixture vacío, una métrica sin registrar): eso es un fallo, no un entorno.
Si añadís un skip nuevo, incluí siempre el motivo en el mensaje.

## Configuración de cobertura

Definida en `pyproject.toml` bajo `[tool.coverage.*]`:

- **Branch coverage**: activado (`branch = true`).
- **Fuentes medidas**: `api`, `db`, `scraper`, `scheduler`, `services`, `shared`, `observability`, `config`, `llm`, `mcp_server`.
- **`fail_under`**: 78% — el build falla si la cobertura baja de este umbral.
- **Líneas excluidas**:
  - `pragma: no cover`
  - `if __name__ == "__main__":`
  - `if TYPE_CHECKING:`
  - `raise NotImplementedError`
- **Archivos omitidos**: `tests/*`, `*/__pycache__/*`, `scripts/*`, `scheduler/register_daily_task_windows.ps1`.

El reporte se genera automáticamente con `--cov-report=term-missing` (configurado en `addopts`).

Para un reporte HTML:

```bash
make coverage-html   # genera htmlcov/index.html
```
