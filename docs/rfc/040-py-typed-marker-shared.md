---
rfc: 040
title: Add PEP 561 py.typed marker to shared/ package
issue: https://github.com/Dkalds/Licitaciones_sap_SP/issues/40
author: agent:architect
date: 2026-05-24
status: implemented
---

## Contexto

PEP 561 requiere un archivo `py.typed` en paquetes que exponen type hints para que herramientas como mypy los reconozcan. `shared/` es un paquete con typing strict en proceso de migración y carece de este marker.

Item P1 del backlog (`docs/IMPROVEMENT_BACKLOG.md`).

## Decisión

1. Crear archivo vacío `shared/py.typed`.
2. Agregar `[tool.setuptools.package-data]` en `pyproject.toml` con `shared = ["py.typed"]`.

NO se hace: agregar `py.typed` a otros paquetes (scope limitado a `shared/`).

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| MANIFEST.in | Estándar legacy | No funciona con setuptools moderno PEP 621 | Obsoleto |
| No hacer nada | Zero effort | mypy no reconoce tipos de shared/ en consumidores | No cumple objetivo |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Positivo — mejora soporte de tipos | — |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno | — |
| §3.4 Auto-marking tests | Ninguno | — |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. Crear `shared/py.typed` (archivo vacío)
2. Agregar sección `[tool.setuptools.package-data]` en `pyproject.toml` después de `[tool.setuptools.packages.find]`

**Archivos de partida**: `shared/`, `pyproject.toml`
**Riesgo estimado**: bajo
**Tiempo estimado**: <1 hora

## Acceptance criteria

- [x] Archivo vacío `shared/py.typed` creado
- [x] `pyproject.toml` incluye `[tool.setuptools.package-data]` con `shared = ["py.typed"]`
- [x] `make lint && make typecheck && make test-unit` pasan en verde

## Notas de review

2026-05-24T18:00Z agent:reviewer — Aprobado. Riesgo bajo, sin impacto en invariantes. Cambio a pyproject.toml es mínimo (1 sección nueva). No afecta seguridad.
