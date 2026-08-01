import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]

try:
    d = json.load(sys.stdin)
    cmd = (d.get("tool_input") or d).get("command", "")
except Exception:
    cmd = ""

GREP_TOKENS = ("grep", "rg ", "ripgrep", "find ", "fd ", "ack ", "ag ")

try:
    if any(tok in cmd for tok in GREP_TOKENS) and (ROOT / "graphify-out/graph.json").is_file():
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "additionalContext": (
                            "graphify: knowledge graph at graphify-out/. For focused questions, "
                            'run `graphify query "<question>"` when the CLI is available; otherwise '
                            "read the committed artifacts before grepping raw files. Read "
                            "GRAPH_REPORT.md only for broad architecture context."
                        ),
                    }
                }
            )
        )
except Exception:
    pass
