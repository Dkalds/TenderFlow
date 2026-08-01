import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]

try:
    d = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    fp = (d.get("tool_input") or d).get("file_path", "")
except Exception:
    fp = ""

try:
    skip = any(
        x in fp
        for x in (
            ".venv",
            "graphify-out",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            "__pycache__",
            "htmlcov",
            "node_modules",
        )
    )
    ok = fp.endswith(".py") and not skip and (ROOT / "graphify-out").is_dir()
    if ok:
        (ROOT / "graphify-out/.graph_stale").touch()
except Exception:
    pass
