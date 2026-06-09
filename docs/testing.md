# Testing

Guía para ejecutar, escribir y entender los tests del proyecto.

## Auto-marking por convención de nombre

`tests/conftest.py` asigna markers automáticamente según tokens en el nombre del archivo o función. **No marcar tests manualmente.**

| Token en nombre                                        | Marker        |
|--------------------------------------------------------|---------------|
| `_e2e`, `visual_regression`, `dashboard_smoke`, `dashboard_pages` | `e2e`         |
| `performance`, `load`                                  | `load`        |
| `property`, `properties`, `property_based`             | `property`    |
| `integration_e2e`                                      | `integration` |
| Todo lo demás                                          | `unit` (default) |

Prioridad de evaluación: e2e > load > property > integration > unit.

Si necesitás que un test tenga otro marker, **renombrá el archivo o la función** — no uses `@pytest.mark.xxx`.

## Fixtures disponibles

| Fixture   | Depende de     | Descripción                                                      |
|-----------|----------------|------------------------------------------------------------------|
| `tmp_db`  | `monkeypatch`, `tmp_path` | BD SQLite temporal con migraciones aplicadas. Aislada por test. Devuelve `(db_mod, tmp_path)`. |
| `api_db`  | `tmp_path`, `monkeypatch` | BD temporal con todas las migraciones, orientada a tests de API. Devuelve `db_path`. |
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
make test-unit         # unit (sin slow) — usar durante desarrollo
make test              # suite completa excepto integration_e2e y dashboard_smoke
make test-all          # todo excepto integration
make test-integration  # solo integration
make test-e2e          # solo e2e
make test-property     # solo property
make test-load         # solo load
make test-perf         # test_performance.py con timeout 120s
make test-smoke        # test_dashboard_smoke.py
```

## Skips condicionales

Algunos tests se saltan **a propósito** según el entorno. No son deuda: cada
`pytest.skip` lleva un motivo explícito. Política:

| Test | Condición de skip | Por qué es correcto |
|------|-------------------|---------------------|
| `test_shared_schemas.py` | `pandera` no instalado (`importorskip`) o `LicitacionSchema` es NoOp | La validación pandera es un extra opcional (`[schemas]`); sin él el schema degrada a NoOp y no hay nada que validar. |
| `test_unit_coverage_batch1b.py::TestFallbackActors` | `dramatiq` **sí** está instalado | Estos tests cubren el camino *fallback* (sin broker). Con dramatiq activo, el fallback no se ejecuta. |
| `test_visual_regression.py` | El puerto 8599 ya está en uso | Evita chocar con un dashboard de desarrollo ya levantado. |

Regla general: usar `pytest.importorskip("dep")` para dependencias opcionales y
`pytest.skip(motivo)` con un mensaje claro para condiciones de entorno. En CI,
las dependencias opcionales relevantes (`pandera`, etc.) **sí** se instalan, de
modo que estos paths se ejercitan; los skips solo aplican en entornos locales
mínimos. Si añadís un skip nuevo, incluí siempre el motivo en el mensaje.

## Configuración de cobertura

Definida en `pyproject.toml` bajo `[tool.coverage.*]`:

- **Branch coverage**: activado (`branch = true`).
- **Fuentes medidas**: `api`, `db`, `scraper`, `scheduler`, `services`, `shared`, `observability`, `config`, `dashboard`, `llm`.
- **`fail_under`**: 70% — el build falla si la cobertura baja de este umbral.
- **Líneas excluidas**:
  - `pragma: no cover`
  - `if __name__ == "__main__":`
  - `if TYPE_CHECKING:`
  - `raise NotImplementedError`
- **Archivos omitidos**: `tests/*`, `__pycache__`, helpers de dashboard (`chart_helpers.py`, `lazy.py`), `observability/prometheus.py`, `observability/tracing.py`, `scripts/*`.

El reporte se genera automáticamente con `--cov-report=term-missing` (configurado en `addopts`).

Para un reporte HTML:

```bash
make coverage-html   # genera htmlcov/index.html
```
