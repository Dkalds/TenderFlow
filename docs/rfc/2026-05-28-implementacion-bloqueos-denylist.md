---
title: "RFC de handoff humano: bloqueos por denylist"
author: "agent:architect"
date: 2026-05-28
status: partially-implemented
tags: [rfc]
---

# RFC de handoff humano: bloqueos por denylist (2026-05-28)

## Contexto breve

Durante la ejecucion del agente se identificaron cambios necesarios que no pudieron aplicarse por restricciones de escritura en rutas denylist. Este documento concentra esos bloqueos para que una persona los ejecute de forma segura y trazable.

## Bloqueos identificados

| Archivo | Estado | Razon | Accion humana |
|---|---|---|---|
| `docs/rfc/2026-05-28-implementacion-bloqueos-denylist.md` | Bloqueado (en origen) | `docs/rfc/**` estaba restringido para el modo activo durante la ejecucion original | Crear/validar este RFC en `docs/rfc/` y mantenerlo como registro canonico del handoff |
| `tests/conftest.py` | Resuelto | Acceso habilitado para esta tanda | Auto-marking de `integration` ampliado con convencion por ruta/nombre y helper de inferencia con prioridad estable |
| `tests/test_markers_automarking.py` (o equivalente en `tests/`) | Resuelto | Acceso habilitado para esta tanda | Agregado test unitario dedicado para reglas de auto-marking y precedencia de markers |
| `.github/workflows/**` | Parcial | Acceso habilitado para esta tanda | Se separo CI en jobs `test-unit` y `test-integration`; resta validar ejecucion en CI remoto |
| `pyproject.toml` | Parcial | Acceso habilitado para esta tanda | Se agregaron overrides de `cryptography` para mypy; resta validar typecheck completo en entorno limpio |
| `requirements*.txt` | No ejecutado por restriccion | Patron en denylist | Gestionar manualmente nuevas dependencias de tooling, observabilidad o graphify |
| `db/alembic/**` | No ejecutado por restriccion | Ruta en denylist | Si corresponde, crear nuevas revisiones Alembic sin modificar migraciones existentes |

## Orden recomendado de ejecucion

1. Validar en CI remoto los jobs `test-unit` y `test-integration`.
2. Ejecutar checks locales completos: lint, typecheck y unit tests en shell limpio.
3. Confirmar que los nuevos patrones de integration no sobre-marcan tests unitarios.
4. Solo si surge del paso anterior, ajustar `pyproject.toml` o `requirements*.txt`.
5. Si hay impacto de esquema, crear revision nueva en `db/alembic/**` (append-only).
6. Re-ejecutar suite relevante y dejar evidencia en PR/issue.

## Checklist de cierre

- [x] Auto-marking de integration actualizado en `tests/conftest.py`.
- [x] Tests nuevos/actualizados en `tests/` validando reglas y precedencia.
- [ ] `make lint` en verde.
- [ ] `make typecheck` en verde.
- [ ] `make test-unit` en verde.
- [ ] Cambios de CI evaluados y, si aplica, implementados.
- [ ] Sin cambios prohibidos fuera del alcance acordado.
- [ ] Evidencia de ejecucion y decision loggeada en PR/issue.
