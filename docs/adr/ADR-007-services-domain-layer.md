# ADR-007 — Capa `services/` como dominio compartido

* **Estado:** Aceptado
* **Fecha:** 2026-05-19
* **Contexto técnico:** Refactor F1 (separación dashboard ↔ dominio)

## Contexto

Hasta ahora, módulos con lógica de dominio puro vivían bajo `dashboard/`:

* `dashboard/normalize.py` — normalización de nombres de empresa, NIF y UTEs.
* `dashboard/classifiers.py` — diccionarios CPV, detección de módulos SAP,
  tecnologías, tipos de proyecto, decoders de estado/tipo de contrato.
* `dashboard/forecast.py` — proyecciones de fin de contrato.

Esto provoca tres problemas:

1. **Acoplamiento UI ↔ dominio**: la API REST y el scheduler no pueden
   reutilizar la lógica sin importar transitivamente Streamlit.
2. **Testabilidad**: los tests unitarios arrastran dependencias innecesarias
   (plotly, streamlit) sólo para validar funciones puras.
3. **Coverage por capa**: imposible aplicar umbrales distintos a UI vs
   dominio (la UI es difícil de testear al 80 %, el dominio sí).

## Decisión

Migrar la lógica de dominio a `services/`:

* `services/normalization.py` — `normalize_company`, `normalize_nif`,
  `parse_ute_members`. Sin dependencias UI.
* `services/classification.py` — diccionarios CPV/SAP/tecnologías y
  funciones puras de etiquetado. Re-exporta `NUTS3_TO_CCAA` /
  `nuts_to_ccaa` desde `shared.geo`.
* `dashboard/normalize.py` y `dashboard/classifiers.py` se mantienen como
  **shims de compatibilidad** (~20-40 líneas) que re-exportan desde
  `services/`. Esto evita romper imports existentes en el dashboard y en
  los tests.

Se **omite** `services/forecast.py` por ahora: `dashboard/forecast.py`
arrastra `statsmodels` y no tiene consumidor en API. Se migrará cuando
la API exponga endpoints `/forecast`.

## Consecuencias

**Positivas**

* La API (`api/routes/*`) puede importar de `services/` sin Streamlit.
* Tests unitarios de `services/` corren sin instalar el extra UI.
* Permite umbrales de coverage diferenciados (ver
  `scripts/check_coverage_per_module.py`: `services/` 70 %, `dashboard/pages/` 40 %).

**Negativas / costes**

* Shims duplican mantenimiento: cada export nuevo en `services/` debe
  añadirse también a la lista `__all__` del shim si se quiere accesible
  desde `dashboard.*`.
* Imports circulares potenciales: `services/` no debe importar de
  `dashboard/`. Validado por `ruff` con regla `TID252` activa.

## Alternativas consideradas

1. **Mover archivos sin shim (rompe API)**: requeriría refactor masivo
   de imports en una sola PR. Descartado por riesgo.
2. **Mantener todo en `dashboard/` y exponer vía `from dashboard.x import y`
   desde API**: arrastra Streamlit al runtime de la API. Descartado.
3. **Inyección de dependencias con Protocol**: sobre-ingeniería para
   funciones puras; descartado.

## Verificación

```bash
# Los shims deben mantener backward compatibility
python -c "from dashboard.normalize import normalize_company, normalize_nif, parse_ute_members; print('OK')"
python -c "from dashboard.classifiers import cpv_label, detect_modules, estado_label; print('OK')"

# Y las nuevas rutas canónicas deben funcionar también
python -c "from services.normalization import normalize_company; print('OK')"
python -c "from services.classification import cpv_label, SAP_MODULES; print('OK')"
```

## Referencias

* ADR-002 — Streamlit vs FastAPI + React.
* `scripts/check_coverage_per_module.py` — umbrales por capa.
