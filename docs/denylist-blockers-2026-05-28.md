# Bloqueos por denylist - 2026-05-28

Objetivo: dejar trazabilidad exacta de cambios pendientes que requieren intervencion humana por restricciones de ruta del agente en esta ejecucion.

## Pendientes bloqueados

1. Archivo solicitado: `docs/rfc/2026-05-28-implementacion-bloqueos-denylist.md`
   - Estado: bloqueado.
   - Razon: `docs/rfc/**` esta en denylist del modo coder.
   - Accion humana sugerida: crear ese archivo en `docs/rfc/` y copiar el contenido de este documento.

2. Archivo: `tests/conftest.py`
   - Estado: resuelto en esta tanda.
   - Razon: se habilito edicion directa.
   - Resultado: auto-marking de `integration` ampliado por convencion de ruta/nombre con prioridad estable.

3. Archivo nuevo en `tests/` (ej. `tests/test_markers_automarking.py`)
   - Estado: resuelto en esta tanda.
   - Razon: se habilito edicion directa.
   - Resultado: agregado test unitario para validar reglas de auto-marking y precedencia.

4. Archivos potenciales de CI: `.github/workflows/**`
   - Estado: parcialmente resuelto.
   - Razon: se habilito edicion directa.
   - Resultado: CI separado en jobs de unit e integration; pendiente validar ejecucion remota.

5. Archivo potencial: `pyproject.toml`
   - Estado: parcialmente resuelto.
   - Razon: se habilito edicion directa.
   - Resultado: agregado ignore_missing_imports para `cryptography`/`cryptography.*`; pendiente validacion end-to-end.

6. Archivos potenciales: `requirements*.txt`
   - Estado: no ejecutado por restriccion.
   - Razon: denylist explicita.
   - Cambio pendiente exacto: cualquier dependencia nueva para tooling/observabilidad/graphify debe gestionarla humano.

7. Archivos potenciales: `db/alembic/**`
   - Estado: no ejecutado por restriccion.
   - Razon: denylist explicita.
   - Cambio pendiente exacto: consolidacion de migraciones que implique nuevas revisiones Alembic requiere humano.

## Nota

El avance implementado en esta tanda se concentro en archivos permitidos: scheduler, scripts, Makefile y docs fuera de `docs/rfc/**`.
