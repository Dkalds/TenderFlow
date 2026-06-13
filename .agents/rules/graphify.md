---
trigger: always_on
description: Consult the graphify knowledge graph at graphify-out/ for codebase and architecture questions.
---

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- For codebase or architecture questions, when `graphify-out/graph.json` exists, first run `graphify query "<question>"` (CLI) or `query_graph` (MCP). Use `graphify path "<A>" "<B>"` / `shortest_path` for relationships and `graphify explain "<concept>"` / `get_node` for focused concepts. These return a scoped subgraph, usually much smaller than `GRAPH_REPORT.md` or raw grep output.
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)
- The `graphify` CLI is a maintainer-local tool, NOT on PyPI/npm — never try to install it. If the CLI is missing: read the committed artifacts (`graphify-out/graph.json` / `wiki/` / `GRAPH_REPORT.md`) directly; if `graphify-out/` is absent entirely, fall back to grep + docs/AGENT_PLAYBOOK.md and skip all `graphify` commands (including the post-edit `graphify update .`).
