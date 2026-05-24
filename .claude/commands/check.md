---
description: Corre lint + typecheck + tests rápidos antes de declarar un cambio listo
---

Ejecuta el ciclo de validación estándar del proyecto y reporta un resumen conciso.

Pasos (en orden, no abandones si uno falla — sigue al siguiente y reporta todo):

1. **Lint**: `make lint` (ruff check .)
2. **Typecheck**: `make typecheck` (mypy .)
3. **Tests unit rápidos**: `make test-unit` (pytest -m "unit and not slow")

Para cada paso reportá: ✅ pasó / ❌ falló (con primeras 5-10 líneas del error). Si hay fallos, **no intentes arreglarlos automáticamente** — listá los archivos afectados y esperá indicación del usuario.

Al final, si todo pasó verde:
- Recordá correr `graphify update .` si hubo cambios estructurales (nuevos módulos, renames).
- Mostrá el comando para correrlo: `graphify update .` o `/graph-refresh`.
