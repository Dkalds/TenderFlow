import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]


def raiz_del_checkout(*pistas: str) -> pathlib.Path:
    """El checkout donde trabaja la sesión, que no siempre aloja este fichero.

    En un worktree de Claude Code los hooks se lanzan desde el checkout
    principal (`$CLAUDE_PROJECT_DIR`), así que la raíz deducida de `__file__`
    es la de otro árbol. Las pistas —el `cwd` que manda el cliente, la ruta que
    se edita— dicen cuál es el de verdad: el primer ancestro con `.git`
    (directorio en el checkout principal, fichero en un worktree).
    """
    for pista in pistas:
        if not pista:
            continue
        inicio = pathlib.Path(pista)
        if not inicio.is_absolute():
            continue
        for candidato in (inicio, *inicio.parents):
            if (candidato / ".git").exists():
                return candidato
    return ROOT


try:
    d = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    fp = (d.get("tool_input") or d).get("file_path", "")
    cwd = str(d.get("cwd") or "")
except Exception:
    fp = ""
    cwd = ""

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
    raiz = raiz_del_checkout(fp, cwd)
    ok = fp.endswith(".py") and not skip and (raiz / "graphify-out").is_dir()
    if ok:
        (raiz / "graphify-out/.graph_stale").touch()
except Exception:
    pass
