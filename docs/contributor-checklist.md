# Checklist breve para contributors

## Pre-flight

1. Si el CLI esta disponible, corre `graphify query "area relevante"`; si no,
   lee los artefactos commiteados siguiendo AGENTS.md §1.
2. Revisa invariantes en AGENTS.md (typing strict, upsert idempotente, migraciones append-only).
3. Identifica si tu cambio toca rutas sensibles (workflows, pyproject, requirements, alembic, secrets).
4. Si toca rutas sensibles, pide OK humano explicito antes de editar.

## Post-flight

1. Ejecuta checks locales:
   - `make lint`
   - `make typecheck`
   - `make test-unit`
2. Refresca graphify (solo si el CLI esta instalado; no hay targets `make` para esto):
   - `graphify update .`
   - usa `graphify update . --force` solo con renames/moves/deletes.
3. Si cambias convenciones, actualiza documentacion tecnica en `docs/`.
4. Si tocaste instrucciones de agentes, corre `make check-agent-docs`.
5. Si necesitas una accion de la lista de AGENTS.md §6 (migraciones, secretos, workflows,
   dependencias, PRs), para y pedi OK explicito antes de ejecutarla.
