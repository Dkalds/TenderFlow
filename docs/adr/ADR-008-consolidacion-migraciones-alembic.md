---
id: ADR-008
title: "Consolidación hacia Alembic como sistema canónico de migraciones"
status: accepted
date: 2026-05-23
deciders: "Daniel Kalitovics"
supersedes: "[[ADR-003-migraciones-caseras-plus-alembic]]"
related:
  - "[[ADR-003-migraciones-caseras-plus-alembic]]"
tags: [adr]
---

# ADR-008: Consolidación hacia Alembic como sistema canónico de migraciones

**Status:** Accepted  
**Date:** 2026-05-23  
**Deciders:** Daniel Kalitovics  
**Supersedes:** [[ADR-003-migraciones-caseras-plus-alembic|ADR-003]] (parcialmente — actualiza la decisión de coexistencia)

## Context

[[ADR-003-migraciones-caseras-plus-alembic|ADR-003]] estableció un sistema dual: migraciones custom (`db/migrations.py`) para
v1-v13 y Alembic para v14+. En la práctica, el sistema custom continuó creciendo
hasta v32, creando un solapamiento con las migraciones Alembic (v14-v21 existen en
ambos sistemas con contenido similar pero no idéntico).

Este solapamiento generaba:

1. **Confusión sobre la fuente de verdad**: ¿cuál de los dos sistemas es el
   autoritativo para la versión 20?
2. **Riesgo de divergencia**: un cambio en un sistema no se refleja en el otro.
3. **Complejidad operacional**: nuevos desarrolladores deben entender dos sistemas
   con sus propias convenciones, comandos y estados.
4. **Cobertura de tests parcial**: los tests de migraciones cubren `db/migrations.py`
   pero no verifican equivalencia con las migraciones Alembic equivalentes.

## Decision

**Alembic es el sistema canónico único de migraciones a partir de v22.**

- `db/migrations.py` se mantiene en modo **solo lectura / compatibilidad** para
  bases de datos existentes que todavía no han sido migradas a Alembic.
- No se añaden nuevas migraciones a `db/migrations.py`.
- Todas las migraciones nuevas van a `db/alembic/versions/`.
- El `Makefile` actualiza `migrate` con nota de deprecación y añade
  `migrate-status` y `migrate-history` para Alembic.

## Rationale

- **Un solo comando para nuevas BDs**: `alembic upgrade head` aplica toda la
  cadena v14-v22+ sin necesidad de `apply_pending()` adicional.
- **Autogenerate**: `alembic revision --autogenerate` detecta divergencias entre
  el schema Python y la BD real, reduciendo errores humanos.
- **Historial visible**: `alembic history --verbose` muestra toda la cadena de
  cambios en orden.
- **Rollback estándar**: `alembic downgrade -1` es predecible y testeable en CI.

## Consecuencias

### Positivas
- Un solo sistema que entender para nuevas migraciones.
- `alembic upgrade head` es idempotente y seguro de ejecutar en CI.
- El sistema custom sigue funcionando para BDs legacy sin cambios disruptivos.

### Negativas
- BDs legacy deben correr `apply_pending()` + `alembic stamp baseline001` +
  `alembic upgrade head` para sincronizarse con Alembic (ver runbook abajo).
- Los rollbacks de v1-v32 del sistema custom siguen disponibles solo vía
  `db.migrations.rollback()`, no vía `alembic downgrade`.

## Procedimiento de migración para BDs legacy

```bash
# 1. Asegurar que todas las migraciones custom están aplicadas
python -c "from db.database import init_db; init_db()"

# 2. Verificar versión actual del sistema custom
python -c "from db.connection import connect; from db.migrations import current_version; \
           print('version custom:', [current_version(c) for c in [__import__('contextlib').ExitStack().__enter__(connect())]][0])"

# 3. Stampear el baseline Alembic (indica que v1-v13 ya están aplicadas)
alembic stamp baseline001

# 4. Aplicar migraciones Alembic pendientes (v14-v22+)
alembic upgrade head

# 5. Verificar estado final
alembic current
```

## Alternativas Consideradas

| Alternativa | Razón rechazada |
|-------------|----------------|
| Migrar v1-v32 del custom a Alembic retroactivamente | Alto riesgo de romper BDs existentes; el sistema custom funciona |
| Mantener ambos sistemas en paralelo permanentemente | Deuda técnica creciente; fuente de confusión continua |
| Eliminar Alembic y usar solo custom | Perdería autogenerate, CLI estándar y compatibilidad con herramientas del ecosistema |
