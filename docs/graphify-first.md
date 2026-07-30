# Graphify-first operativo

Esta guia define el uso diario de graphify para navegar arquitectura antes de leer archivos en crudo.

## Comandos practicos

`graphify` es un CLI local del mantenedor, no un target del Makefile (no hay
`make graphify-*`). Se invoca directo:

```bash
graphify query "donde se calcula la calidad de datos"
graphify path "api.app" "services.licitaciones"
graphify explain "scheduler.loop"
graphify update .
graphify update . --force
```

En Claude Code, `/graph-refresh` envuelve el `update` con verificacion de mtime y
limpieza del flag `.graph_stale`.

## Cuando usar --force

Usa `graphify update . --force` en estos casos:

- Renombraste archivos o modulos.
- Moviste archivos entre paquetes.
- Borraste simbolos/archivos importantes.
- El grafo quedo stale tras refactor estructural.

En cambios pequenos (ediciones internas sin renames/moves), usa `graphify update .` incremental.

## Fallback si graphify no esta instalado

Si el comando `graphify` no existe en tu shell (CI, sesiones remotas):

1. Lee los artefactos commiteados: `graphify-out/graph.json`, `graphify-out/wiki/`
   o `GRAPH_REPORT.md`. Siguen siendo utiles sin el CLI.
2. Si `graphify-out/` no existe, navega con `rg` + `docs/AGENT_PLAYBOOK.md` y
   omite todos los comandos `graphify` (incluido el `update` de post-flight).
3. Documenta en el PR que no se pudo regenerar el grafo en local.
4. Mantene la regla graphify-first para entornos donde la herramienta este disponible.
