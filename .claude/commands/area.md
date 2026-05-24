---
description: Onboarding rápido a un área del código (graphify explain + files + tests + docs)
argument-hint: <nombre del paquete o concepto>
---

Querés trabajar en `$ARGUMENTS`. Da un panorama denso y accionable, en este orden:

1. **Si `graphify-out/graph.json` existe**: ejecutá `graphify explain "$ARGUMENTS"` — copiá el output relevante (god nodes, vecinos clave, paquete al que pertenece).
2. **Archivos del paquete**: si `$ARGUMENTS` es un paquete (`services`, `api`, `db`, `dashboard`, `scraper`, `scheduler`, `config`, `shared`, `observability`, `llm`), listá `ls <paquete>/` con tamaño en líneas de cada `.py`.
3. **Entry point**: identificá el archivo principal (mirando `docs/AGENT_PLAYBOOK.md` sección 1, "Mapa detallado de paquetes").
4. **Tests asociados**: `ls tests/test_<area>*.py` o `grep -l "from <area>" tests/`. Indicar coverage rápido si hay datos en `.coverage` o `cov80.txt`.
5. **Docs relacionados**: revisar `docs/AGENT_PLAYBOOK.md` columna "Docs relacionados" del paquete + `docs/adr/` por nombre.
6. **Estado de typing**: ¿strict o no? (consultar `pyproject.toml` sección `[tool.mypy]` overrides — si el paquete tiene `disallow_untyped_defs = false`, NO es strict).
7. **Invariantes específicos**: mencionar los del paquete si están en AGENTS.md sección 3 o playbook sección 3.

**Output esperado**: un brief de ~30 líneas que sirva como context-pack para empezar a trabajar. No te metas en detalles de implementación — solo orientación.

Si `$ARGUMENTS` está vacío, pedí al usuario: "¿Sobre qué área? Ej: `services`, `scraper`, `db/repositories`, `api/routes`, `dashboard/pages`, o un concepto como `upsert`, `auth`, `CPV`."
