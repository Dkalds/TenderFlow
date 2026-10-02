# Issue #56 — Condición incorrecta en tracing.py

**Fecha**: 2026-05-24
**Issue**: https://github.com/Dkalds/Licitaciones_sap_SP/issues/56
**RFC**: docs/rfc/056-fix-tracing-condition.md
**Estado**: Implementado, pendiente de review humano

## Resumen

Bug en `observability/tracing.py:232`: la condición `if _noop and not _configured` no hacía bypass cuando `configure_tracing()` nunca se llamaba (`_noop=False, _configured=False`).

## Decisión

Cambiar a `if not _configured or _noop:` para cubrir tanto el caso no-configurado como el NoOp explícito.

## Discusión

- **architect**: Fix directo, bajo riesgo. Alternativa de cambiar default de `_noop` descartada por confusión semántica.
- **reviewer**: Cambio correcto, cubre los 3 estados posibles.
- **security_triage**: Sin impacto de seguridad.
- **test_engineer**: 2 tests nuevos añadidos para los casos de bypass.
