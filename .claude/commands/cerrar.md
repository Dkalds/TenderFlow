---
description: Tras el merge, quita los worktrees y ramas locales cuyo trabajo ya está en master
---

Cierra el ciclo de las ramas de agente: cada sesión abre un worktree y una rama `agente/*`, y nada los quita después del merge.

1. **Inventario**: desde el checkout principal, `python scripts/cerrar_ramas.py`. Cruza cada rama con `origin/master` y con los PR de GitHub (`gh`), porque los PR se integran con squash y `git branch --merged` no los ve. Agrupa: integradas, integradas con cambios sin commitear, worktrees sin commits propios (pueden ser sesiones recién abiertas), mergeadas con commits posteriores, PR abierto, PR cerrado sin merge y sin PR. Guarda las integradas como el inventario que se aprueba.
2. **Mostrá el inventario al usuario** con los recuentos por grupo y pedí OK explícito para borrar el grupo «integrada» (AGENTS.md §6: borrar ramas requiere confirmación). Los demás grupos solo se informan; no propongas borrarlos en bloque.
3. **Con el OK**: `python scripts/cerrar_ramas.py --borrar`. Borra solo lo que el inventario aprobado listó y sigue integrado; lo que se haya integrado entre una pasada y otra se deja. Va sin `--force`: un worktree con cambios o ficheros sin seguir se conserva y sale en el informe, pero los ignorados (`.env*`, `data/*`, `node_modules`) se van con él; si alguno importa, decíselo al usuario antes del OK. Las ramas remotas no se tocan.
4. **Backlog**: para cada PR recién mergeado de esta sesión, comprobá que el ítem que cerraba ya no está en `docs/IMPROVEMENT_BACKLOG.md` (o que su **Estado actual** refleja el avance parcial). Si falta, decíselo al usuario; no lo edites desde aquí.

Reportá cuántos worktrees y ramas se quitaron, cuáles fallaron y por qué.
