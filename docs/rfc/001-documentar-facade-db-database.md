---
rfc: 001
title: Documentar la fachada db.database
issue: "(test local — sin issue de GitHub)"
author: agent:architect
date: 2026-05-24
status: implemented
supersedes: ~
---

## Contexto

`db/database.py` es el punto de entrada único al subsistema de persistencia del
proyecto. Actualmente ya contiene un docstring de módulo, pero éste es breve y
no lista explícitamente los símbolos reexportados por cada submódulo.

Según AGENTS.md §2, `db.database` es la *fachada* canónica:

> `db/` — `db/database.py` (fachada → `connection/schema/upsert`)

El AGENT_PLAYBOOK §1 también lo menciona explícitamente. Sin embargo, ningún
documento describe el patrón de fachada como decisión arquitectónica ni lista
en detalle qué reexporta cada submódulo, lo que dificulta la navegación y
onboarding.

ADRs relacionados:
- **ADR-001** (SQL crudo vs ORM) — establece el uso de SQL directo con
  repositorios finos. La fachada es consecuencia directa de ese diseño.
- **ADR-004** (SQLite/Turso) — define los dos backends soportados
  (SQLite local y Turso/libSQL cloud).

## Decisión

1. **Reemplazar** el docstring de módulo de `db/database.py` con uno extendido
   que liste los 3 submódulos y cada símbolo reexportado con una línea de
   descripción.
2. **Añadir una sección** "Patrón de fachada `db.database`" en
   `docs/AGENT_PLAYBOOK.md` (sección 3, Patterns por área) que documente la
   convención, los 3 submódulos y cuándo importar desde la fachada vs directo.

**Qué NO se hace:**
- No se modifican tests, migraciones alembic, pyproject.toml ni workflows.
- No se cambian los símbolos reexportados ni el `__all__`.
- No se introducen imports nuevos ni dependencias.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Añadir solo el docstring, sin sección en playbook | Cambio mínimo | El patrón no queda documentado para agentes futuros | No cumple acceptance criteria del backlog |
| Crear ADR nuevo para el patrón de fachada | Visibilidad alta | Un ADR es para *decisiones*, no para describir estado actual ya aceptado | ADR-001 ya cubre la decisión de SQL crudo; la fachada es consecuencia operativa |
| Auto-generar docs con sphinx/mkdocs | Completo | Añade dependencia y complejidad de build | Fuera del scope del ítem P2 (riesgo bajo) |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Ninguno — solo se modifica el docstring de módulo | — |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno | — |
| §3.4 Auto-marking tests | Ninguno | — |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. **`db/database.py`** — reemplazar el docstring de módulo actual con uno
   detallado que liste los 3 submódulos y, para cada uno, los símbolos
   reexportados con descripción de una línea.
2. **`docs/AGENT_PLAYBOOK.md`** — añadir entrada en la tabla de patterns
   (§3) sobre el patrón de fachada `db.database`, incluyendo: propósito,
   submódulos, regla de uso.

**Archivos de partida**: `db/database.py`, `docs/AGENT_PLAYBOOK.md`  
**Riesgo estimado**: bajo  
**Tiempo estimado**: < 1 hora

## Acceptance criteria

- [x] Docstring de módulo en `db/database.py` lista los 3 submódulos
      (`db.connection`, `db.schema`, `db.upsert`) y qué reexporta de cada uno.
- [x] Sección/entrada en `docs/AGENT_PLAYBOOK.md` sobre el patrón de fachada.
- [x] `make lint && make typecheck` pasan en verde (cambio es solo docstring +
      markdown; no afecta typing ni linting de código).
- [x] Sin cambios en `tests/`, `db/alembic/`, `pyproject.toml`,
      `.github/workflows/`.

## Notas de review

2026-05-24T00:00Z agent:reviewer — RFC completo y correcto. La decisión de
  enriquecer el docstring existente en lugar de reemplazarlo es la mínima
  intervención necesaria. El patrón de fachada está bien descrito. La tabla de
  impacto en invariantes es correcta (cambio puramente documental). Aprobado.
