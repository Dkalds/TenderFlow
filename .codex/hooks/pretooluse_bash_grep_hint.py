import json
import os
import sys

try:
    d = json.load(sys.stdin)
    cmd = (d.get("tool_input") or d).get("command", "")
except Exception:
    cmd = ""

GREP_TOKENS = ("grep", "rg ", "ripgrep", "find ", "fd ", "ack ", "ag ")

try:
    if any(tok in cmd for tok in GREP_TOKENS) and os.path.isfile("graphify-out/graph.json"):
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": (
                    "graphify: knowledge graph at graphify-out/. For focused questions, "
                    "run `graphify query \"<question>\"` (scoped subgraph, usually much "
                    "smaller than GRAPH_REPORT.md) instead of grepping raw files. Read "
                    "GRAPH_REPORT.md only for broad architecture context."
                ),
            }
        }))
except Exception:
    pass
