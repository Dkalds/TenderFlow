---
rfc: 056
title: Fix incorrect condition in tracing.py that allows spans without OpenTelemetry configured
issue: https://github.com/Dkalds/Licitaciones_sap_SP/issues/56
author: agent:architect
date: 2026-05-24
status: implemented
---

## Contexto

En `observability/tracing.py`, el decorador `@traced` usa la condición `if _noop and not _configured` (línea 232) para decidir si hacer bypass del tracing. Cuando `configure_tracing()` nunca se llama, ambas variables son `False`, por lo que la condición evalúa a `False` y el decorador intenta crear spans sin que OpenTelemetry esté configurado. Esto genera spans huérfanos, overhead de CPU innecesario y posibles excepciones silenciadas.

## Decisión

Cambiar la condición de la línea 232 de:
```python
if _noop and not _configured:
```
a:
```python
if not _configured:
```

Esto garantiza que si `configure_tracing()` no se llamó, el decorador siempre hace bypass. El caso `_noop=True, _configured=True` (NoOp configurado explícitamente) sigue cubierto porque `not _configured` es `False` y el flujo continúa al bloque de tracing que ya maneja NoOp tracers correctamente.

**Nota**: Revisando el código, cuando `_noop=True` y `_configured=True`, el tracer devuelto por `get_tracer()` es un NoOp tracer de OpenTelemetry, que crea spans sin overhead real. Pero para mayor eficiencia, también podemos hacer bypass en ese caso. La condición óptima es:

```python
if not _configured or _noop:
```

Esto cubre: (1) nunca configurado → bypass, (2) configurado en modo NoOp → bypass, (3) configurado con endpoint real → tracing activo.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Solo `if not _configured:` | Simple, fix mínimo | NoOp configurado aún crea spans (aunque son NoOp) | Funcional pero subóptimo |
| `if not _configured or _noop:` | Cubre ambos casos, más eficiente | Cambio ligeramente mayor | **Elegida** |
| Inicializar `_noop = True` por defecto | Fix sin cambiar la condición | Cambia semántica de estado inicial | Confuso semánticamente |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Ninguno | — |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno | — |
| §3.4 Auto-marking tests | Ninguno | — |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. Cambiar condición en `observability/tracing.py` línea 232
2. Añadir test `test_traced_bypasses_without_configure` en `tests/test_tracing.py`

**Archivos de partida**: `observability/tracing.py`, `tests/test_tracing.py`
**Riesgo estimado**: bajo
**Tiempo estimado**: <1 hora

## Acceptance criteria

- [x] La condición en línea 232 es `if not _configured or _noop:`
- [ ] Test verifica que `@traced` hace bypass cuando `_configured=False`
- [ ] `make lint && make typecheck && make test-unit` pasan en verde

## Notas de review

2026-05-24T00:00Z agent:reviewer — RFC aprobado. Cambio mínimo, bajo riesgo. La condición `not _configured or _noop` es correcta y más eficiente que el estado actual.
