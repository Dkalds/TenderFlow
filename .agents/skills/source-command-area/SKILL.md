---
name: "source-command-area"
description: "Onboarding rápido a un área del código con graphify, archivos, tests y docs"
---

# source-command-area

Use this skill when the user asks to run the migrated source command `area`.

## Command Template

Querés trabajar en `$ARGUMENTS`. Da un panorama denso y accionable, en este orden:

1. **Graphify-first**: si el CLI `graphify` está disponible, ejecutá `graphify explain "$ARGUMENTS"` y copiá el output relevante. Si falta el CLI pero existe `graphify-out/graph.json`, consultá los artefactos commiteados (`wiki/`, `graph.json`) sin intentar instalarlo. Si tampoco hay artefactos, seguí con el playbook y búsqueda de texto.
2. **Archivos del paquete**: si `$ARGUMENTS` es un paquete (`services`, `api`, `db`, `scraper`, `scheduler`, `config`, `shared`, `observability`, `llm`), listá `ls <paquete>/` con tamaño en líneas de cada `.py`.
3. **Entry point**: identificá el archivo principal (mirando `docs/AGENT_PLAYBOOK.md` sección 1, "Mapa detallado de paquetes").
4. **Tests asociados**: `ls tests/test_<area>*.py` o `grep -l "from <area>" tests/`. Indicar coverage rápido solo si existe `.coverage` y la herramienta `coverage` está disponible.
5. **Docs relacionados**: revisar `docs/AGENT_PLAYBOOK.md` columna "Docs relacionados" del paquete + `docs/adr/` por nombre.
6. **Estado de typing**: confirmar el invariante strict global de `AGENTS.md` y mencionar únicamente overrides relevantes de tests/scripts si afectan al área.
7. **Invariantes específicos**: mencionar los del paquete si están en AGENTS.md sección 3 o playbook sección 3.

**Output esperado**: un brief de ~30 líneas que sirva como context-pack para empezar a trabajar. No te metas en detalles de implementación — solo orientación.

Si `$ARGUMENTS` está vacío, pedí al usuario: "¿Sobre qué área? Ej: `services`, `scraper`, `db/repositories`, `api/routes`, o un concepto como `upsert`, `auth`, `CPV`."
