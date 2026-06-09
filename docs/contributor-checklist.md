# Checklist breve para contributors

## Pre-flight

1. Si existe `graphify-out/graph.json`, corre una consulta inicial:
   - `make graphify-query Q="area relevante"`
2. Revisa invariantes en AGENTS.md (typing strict, upsert idempotente, migraciones append-only).
3. Identifica si tu cambio toca rutas sensibles (workflows, pyproject, requirements, alembic, secrets).
4. Si toca rutas sensibles, pide OK humano explicito antes de editar.

## Post-flight

1. Ejecuta checks locales:
   - `make lint`
   - `make typecheck`
   - `make test-unit`
2. Refresca graphify:
   - `make graphify-update`
   - usa `make graphify-update-force` solo con renames/moves/deletes.
3. Si cambias convenciones, actualiza documentacion tecnica en `docs/`.
4. Si hay bloqueos por denylist, deja evidencia en un archivo de plan para handoff humano.
