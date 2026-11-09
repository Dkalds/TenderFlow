---
description: Escanea el proyecto buscando oportunidades de mejora y reporta priorizado
---

Tu misión: devolver un reporte priorizado de mejoras que el usuario pueda accionar, partiendo de lo que el proyecto ya sabe que le falta y añadiendo solo lo nuevo que esté verificado.

**No modifiques ningún archivo.** Solo análisis read-only.

## 1. Lo que ya está priorizado

`make backlog-estado` (sin `make`: `python scripts/check_backlog_freshness.py --estado`). Da título, prioridad, clase y **Estado actual** de cada ítem de `docs/IMPROVEMENT_BACKLOG.md`. Es la primera fuente (AGENTS.md §0). Lee el **Estado actual**, no el **Problema**, que se queda en el día en que se abrió.

El orden no es el de esa salida, que va por P0–P3: lo fija la tabla de olas de la sección «Plan 2026-10» del backlog, que `backlog-estado` no muestra. Reportá los ítems por ola; los de la fila «Aplazados» van como aplazados, no como pendientes, y lo que la tabla no nombra va después, por prioridad.

Cada ítem va en «Del backlog» con su clase, sea cual sea. La sección «Acciones del propietario» del backlog (antes de `## P0`, tampoco sale en `backlog-estado`: leela en el fichero) se resume aparte, como lo que no es código.

## 2. Fuentes de mejoras nuevas

Para cada una, descartá lo que ya cubre un ítem del paso 1.

- **Deuda declarada**: `git grep -n 'shortcut:'`. Cada atajo dice su límite y cuándo subirlo (AGENTS.md §0); es mejora si ese «cuándo» ya llegó.
- **Ratchets que solo encogen**: las cifras de `docs/STATUS.md` (TID251, `user_key`, capas…), generado por `make status`. Cada entrada de esas listas es una mejora acotada: sacarla del ratchet.
- **Frontend y producto**: las secciones «Lo que queda» de `docs/UX_AUDIT.md`.
- **`# type: ignore` sin motivo**: `git grep -n 'type: ignore' -- ':!tests' ':!scripts'`; cada uno lleva un comentario inline que lo explique (AGENTS.md §3.1), y ningún gate lo comprueba.
- **Tests saltados**: `git grep -n -E 'pytest\.(skip|xfail)|mark\.(skip|xfail)' -- tests` con su motivo; es mejora si el motivo ya no se sostiene.
- **Módulos sin test**: los tests se nombran por categoría (`test_unit_*`, `test_escenario_*`…), no por módulo, así que no se emparejan por nombre. Para un módulo de `services/`, `db/` o `api/routes/` que te parezca crítico, `python scripts/code_map.py importadores <módulo>` dice cuántos tests lo importan.
- **Lo que hayas visto al leer el código** para otra cosa, con su `file:línea`.

No busques violaciones *nuevas* de lo que ya vigila un gate (`Any` con `check_any_count.py`, SQL fuera de `db/` con TID251, contrato OpenAPI, imports de capas, ruff): si está en verde, no las hay. Sus entradas congeladas sí son mejora (viñeta de ratchets).

## 3. Verificá cada candidata antes de reportarla

AGENTS.md §0, «Una mejora se verifica antes de proponerla»:

- Contra el código: buscá el símbolo, fichero o setting que la mejora daría por ausente. Si existe, no es una mejora pendiente.
- Contra el backlog del paso 1: si el tema ya tiene ítem, manda su Estado actual.
- Clasificá lo que queda: `código` (hay que escribirlo), `propietario` (el código está; falta una acción que solo hace el dueño), `medir` (falta mirarlo en producción) o `mixto` (más de una; decí cuáles).

## Reporte final

```
## Mejoras detectadas

### Del backlog (por ola del Plan 2026-10)
- [Ola N · P?] título — `clase` — qué queda hoy, del Estado actual
- Aplazados: ...

### Nuevas
#### Alta
- [área] descripción — `código` | `propietario` | `medir` | `mixto` — verificado en: file:símbolo — fuente: shortcut | ratchet | type-ignore | UX_AUDIT | skip | lectura — esfuerzo estimado
#### Media
- ...
#### Baja
- ...

### Acciones del propietario
- ...
```

Priorizá las nuevas por: seguridad/correctness > lo que nota quien usa el producto > mantenibilidad > estética. Dimensioná para los usuarios que vendrán, no para el uso de hoy.

Al final, ofrecé al usuario: "¿Querés que añada las nuevas a `docs/IMPROVEMENT_BACKLOG.md`?" (pero **no lo edites sin confirmación**). Cada ítem nuevo sigue la «Plantilla nueva entrada» del backlog y empieza por su línea **Estado actual (AAAA-MM-DD)**; sin ella, `check_backlog_freshness.py` falla.
