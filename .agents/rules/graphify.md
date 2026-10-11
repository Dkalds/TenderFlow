---
trigger: always_on
description: Consult the graphify knowledge graph (or scripts/code_map.py when the CLI is missing) for codebase and architecture questions.
---

## graphify

This project uses a graphify knowledge graph. `graphify-out/` is a local cache built by the maintainer's CLI: it is NOT committed, so it only exists on machines that have the CLI.

Rules:
- For codebase or architecture questions, first use `graphify query "<question>"` when the CLI is available, or `query_graph` when the MCP is available. Use `graphify path "<A>" "<B>"` / `shortest_path` for relationships and `graphify explain "<concept>"` / `get_node` for focused concepts. These return a scoped subgraph, usually much smaller than `GRAPH_REPORT.md` or raw grep output.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)
- The `graphify` CLI is a maintainer-local tool, NOT on PyPI/npm — never try to install it. If neither CLI nor MCP is available, use `python scripts/code_map.py` (stdlib only): `simbolo <name>` for a definition and its usages, `importadores <module>` for who imports it, `paquete <package>` / `fichero <path>` for an outline. For anything it does not cover (frontend, SQL, config) fall back to grep + docs/AGENT_PLAYBOOK.md. Skip all `graphify` commands (including the post-edit `graphify update .`).
