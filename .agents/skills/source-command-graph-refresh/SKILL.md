---
name: "source-command-graph-refresh"
description: "Actualiza el knowledge graph (graphify) y verifica que se refrescó"
---

# source-command-graph-refresh

Use this skill when the user asks to run the migrated source command `graph-refresh`.

## Command Template

Re-extrae el código y actualiza `graphify-out/graph.json`. Esto es AST-only (gratis, sin API).

Pasos:

0. Verifica que el CLI existe: `which graphify`. Si no está instalado (CI/sesión remota — es herramienta local del mantenedor, no está en PyPI/npm), reportá eso y pará: no intentes instalarlo ni regenerar el grafo de otra forma.
1. Captura mtime actual de `graphify-out/graph.json` (si existe).
2. Ejecuta: `graphify update .`
3. Si hubo refactor grande (renames, eliminación de módulos), reintenta con: `graphify update . --force`
4. Verifica que `mtime` de `graph.json` cambió. Si no cambió y había edits a .py recientes, reportá warning.
5. Si existe `graphify-out/.graph_stale` (flag que deja el hook PreToolUse `pretooluse_edit_stale.py` al editar un `.py`), borrarlo: `rm graphify-out/.graph_stale`.

Reportá:
- Tamaño antes/después de `graph.json`.
- Si hubo cambio de número de nodos (extraer de `manifest.json` si existe).
- Cualquier warning de graphify (output stderr).

No corras esto en bucle si falla — si hay error real, mostralo y pará.
