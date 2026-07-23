import json
import os
import sys

try:
    d = json.load(sys.stdin)
    fp = (d.get("tool_input") or d).get("file_path", "") or (d.get("tool_input") or d).get("new_path", "")
except Exception:
    fp = ""

# Path denylist por rol de subagente
# Lee la variable de entorno AGENT_ROLE si está seteada por el orchestrator
role = os.environ.get("AGENT_ROLE", "")

denylist_by_role = {
    "architect": [
        lambda p: p.endswith(".py") and "docs/" not in p,
        lambda p: p.startswith("db/alembic/"),
        lambda p: p.startswith(".github/workflows/"),
    ],
    "reviewer": [
        lambda p: True,  # reviewer: ninguna edición permitida
    ],
    "security_triage": [
        lambda p: True,  # security_triage: ninguna edición permitida
    ],
    "test_engineer": [
        lambda p: bool(p) and not p.startswith("tests/"),  # solo tests/
    ],
    "coder": [
        lambda p: p.startswith("db/alembic/"),
        lambda p: p.startswith(".github/workflows/"),
        lambda p: p.startswith(".env"),
        lambda p: p == "pyproject.toml",
        lambda p: "requirements" in p and p.endswith((".txt", ".in")),
        lambda p: p == ".secrets.baseline",
        lambda p: p == ".gitleaks.toml",
        lambda p: p.startswith("tests/"),
    ],
}

try:
    if role and fp and role in denylist_by_role:
        for check in denylist_by_role[role]:
            if check(fp):
                result = {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "additionalContext": (
                            f"PATH DENYLIST BLOCKED: el rol {role!r} no puede editar {fp!r}. "
                            f"Consultá docs/agents/{role}.md para el path_denylist de este rol."
                        ),
                    }
                }
                print(json.dumps(result))
                break
except Exception:
    pass