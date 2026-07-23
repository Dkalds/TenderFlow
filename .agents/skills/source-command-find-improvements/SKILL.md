---
name: "source-command-find-improvements"
description: "Escanea el proyecto buscando oportunidades de mejora y reporta priorizado"
---

# source-command-find-improvements

Use this skill when the user asks to run the migrated source command `find-improvements`.

## Command Template

Tu misión: identificar mejoras concretas en el código y devolver un reporte priorizado que el usuario pueda accionar (o que pueda servir para alimentar `docs/IMPROVEMENT_BACKLOG.md`).

**No modifiques ningún archivo.** Solo análisis read-only.

Pasos:

1. **TODOs / FIXMEs / XXX**: `grep -rn -E "(TODO|FIXME|XXX|HACK)" --include="*.py" --exclude-dir={.venv,.mypy_cache,.ruff_cache,.pytest_cache,__pycache__,graphify-out}` — limita a 30 resultados. Cada uno con archivo:línea + 1 línea de contexto.
2. **Tests skipped**: `grep -rn -E "pytest\.(skip|xfail)" tests/` — listá motivos si hay.
3. **Typing gaps en core**: para cada uno de `services/`, `api/routes/`, `db/repositories/`, busca funciones públicas sin type hints. Usá un grep rápido: funciones `def foo(` sin `->` en la línea o siguiente.
4. **Módulos sin docstring**: para los packages clave (`services`, `api/routes`, `db/repositories`), listá `.py` sin docstring de módulo (primeras 3 líneas no contienen `"""`).
5. **SQL con suppress S608** (`# noqa: S608`): lista. Indicador de tech debt en scraper ML.
6. **Tests con cobertura potencialmente débil**: módulos sin un `test_*` correspondiente. Comparar `ls services/` vs `ls tests/test_services_*.py` etc.
7. **Imports no usados / circulares**: si hay output reciente de ruff, mencionalo (no lo corras de nuevo).

**Reporte final** (formato):

```
## Mejoras detectadas

### Alta prioridad
- [área] descripción — files: X, Y — esfuerzo estimado

### Media
- ...

### Baja
- ...
```

Priorizá por: impacto en seguridad/correctness > impacto en mantenibilidad > nice-to-have estético.

Al final, ofrecé al usuario: "¿Querés que añada estos al `docs/IMPROVEMENT_BACKLOG.md`?" (pero **no lo edites sin confirmación**).
