---
trigger: always_on
description: Consult the graphify knowledge graph (or scripts/code_map.py when the CLI is missing) for codebase and architecture questions.
---

## graphify

Graphify is optional. The CLI package is published as `graphifyy`; do not add it
to project dependencies or install it unless the task asks for Graphify setup.
`graphify-out/` is a local cache and is never committed. The shared VS Code MCP
entry in `.vscode/mcp.json` queries `graphify-out/graph.json`; it requires the
local MCP extra and a graph built on that machine.

Rules:
- For codebase or architecture questions, first use `graphify query "<question>"` when the CLI is available, or `query_graph` when the MCP is available. Use `graphify path "<A>" "<B>"` / `shortest_path` for relationships and `graphify explain "<concept>"` / `get_node` for focused concepts. These return a scoped subgraph, usually much smaller than `GRAPH_REPORT.md` or raw grep output.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context
- After modifying code files in this session, run `graphify update .` when both the CLI and `graphify-out/graph.json` are available to keep the local graph current.
- If neither CLI nor MCP is available, use `python scripts/code_map.py` (stdlib only): `simbolo <name>` for a definition and its usages, `importadores <module>` for who imports it, `paquete <package>` / `fichero <path>` for an outline. For anything it does not cover (frontend, SQL, config) fall back to grep + docs/AGENT_PLAYBOOK.md.
- `graphify extract . --code-only` omits documentation and non-code files. SQL coverage depends on the optional SQL parser. Treat the graph as a navigation aid, not a substitute for reading source files when modifying or debugging.
