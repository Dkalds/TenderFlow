---
name: graphify
description: Consulta o actualiza el knowledge graph del repositorio con fallback local
---

# Workflow: graphify

Seguí la política canónica de [`.agents/rules/graphify.md`](../rules/graphify.md):

1. Si el CLI está disponible, usá `graphify query`, `path`, `explain` o `update` según la intención.
2. Si el CLI no está disponible, no intentes instalarlo. Usá `python scripts/code_map.py` (`simbolo`, `importadores`, `paquete`, `fichero`): lee el código Python desde el AST, sin dependencias.
3. Para lo que eso no cubre, usá `docs/AGENT_PLAYBOOK.md` y búsqueda de texto.

Para actualizar el grafo, el path por defecto es `.`. Tras un update exitoso, eliminá `graphify-out/.graph_stale` si existe.
