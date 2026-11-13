"""PreToolUse(Bash): al commitear o abrir un PR con `web/src/`, recuerda la revisión visual.

Cargar `impeccable` no es hacer su revisión: el PR #647 llegó con UI nueva
revisada solo en código. Cuando el comando es `git commit` o `gh pr create` y
el cambio toca `web/src/`, este hook avisa —sin bloquear— de que mirar las
pantallas renderizadas (o la vista previa de Vercel del PR) es parte del
cambio, y de que si no se hizo hay que decirlo antes de seguir.
"""

import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Solo cuando un comando de la línea empieza por la entrega (tras un separador,
# `env …` o asignaciones): citada en un mensaje de commit es texto. Una línea de
# heredoc que empiece por ella sigue casando; da un aviso de más, no uno de menos.
_ENTREGA = re.compile(
    r"(?:^|[;|&(]|\b(?:then|else|do|time)\b)\s*"
    r"(?:env\b(?:\s+-u\s+\S+|\s+-\S+)*\s+)?"
    r"""(?:\w+=(?:"[^"]*"|'[^']*'|\S+)\s+)*"""
    r"(?:git\s+commit|gh\s+pr\s+create)\b",
    re.MULTILINE,
)

AVISO = (
    "Este cambio toca web/src/ ({ficheros}). La revisión visual de `impeccable` "
    "—mirar las pantallas renderizadas en la vista previa local o en la de "
    "Vercel del PR— es parte del cambio, no un extra. Si no se ha hecho, decíselo "
    "al usuario antes de commitear o abrir el PR, y anotalo en la descripción."
)


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


def ficheros_web(raiz: pathlib.Path) -> list[str]:
    """Ficheros de `web/src/` en lo preparado y en la rama frente a origin/master."""
    vistos: set[str] = set()
    for rango in (["--cached"], ["origin/master...HEAD"]):
        r = subprocess.run(
            ["git", "diff", "--name-only", *rango],  # noqa: S607 - git del PATH, como el resto de hooks
            cwd=raiz,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
        if r.returncode == 0:
            vistos.update(f for f in r.stdout.splitlines() if f.startswith("web/src/"))
    return sorted(vistos)


def main() -> None:
    try:
        d = json.load(sys.stdin)
        cmd = str((d.get("tool_input") or {}).get("command") or "")
        if not _ENTREGA.search(cmd):
            return
        ficheros = ficheros_web(raiz_del_checkout(str(d.get("cwd") or "")))
        if not ficheros:
            return
        muestra = ", ".join(ficheros[:3])
        if len(ficheros) > 3:
            muestra += f" y {len(ficheros) - 3} más"
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "additionalContext": AVISO.format(ficheros=muestra),
                    }
                }
            )
        )
    except Exception:
        return


if __name__ == "__main__":
    main()
