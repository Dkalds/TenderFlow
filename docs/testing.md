# Testing

Guía para ejecutar, escribir y entender los tests del proyecto.

## Auto-marking por convención de nombre + uso de fixtures

`tests/conftest.py` asigna markers automáticamente. **No marcar tests manualmente.**

| Regla                                                  | Marker        |
|--------------------------------------------------------|---------------|
| `_e2e`, `visual_regression` en el nombre               | `e2e`         |
| `performance`, `load`                                  | `load`        |
| `property`, `properties`, `property_based`             | `property`    |
| `integration_e2e` (o `/integration/` en el path)       | `integration` |
| Cierre de fixtures incluye `tmp_db`/`api_db` (BD real) | `integration` |
| Todo lo demás                                          | `unit` (default) |

Prioridad de evaluación: e2e > load > property > integration (nombre) >
integration (fixture PG) > unit.

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
- **Fuentes medidas**: `api`, `db`, `scraper`, `scheduler`, `services`, `shared`, `observability`, `config`, `llm`.
- **`fail_under`**: 70% — el build falla si la cobertura baja de este umbral.
- **Líneas excluidas**:
  - `pragma: no cover`
  - `if __name__ == "__main__":`
  - `if TYPE_CHECKING:`
  - `raise NotImplementedError`
- **Archivos omitidos**: `tests/*`, `__pycache__`, `observability/prometheus.py`, `observability/tracing.py`, `scripts/*`.

El reporte se genera automáticamente con `--cov-report=term-missing` (configurado en `addopts`).

Para un reporte HTML:

```bash
make coverage-html   # genera htmlcov/index.html
```
