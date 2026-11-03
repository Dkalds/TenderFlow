"""PreToolUse(Edit|Write|MultiEdit): no se edita código sin el skill que le toca.

`CLAUDE.md` declara obligatorios unos skills por área y dos PR seguidos se
hicieron sin cargarlos: SQL nuevo en `db/repositories/` sin
`supabase-postgres-best-practices`. Una regla escrita no bastó, así que este
hook busca en el transcript de la sesión una llamada a la herramienta `Skill`
(o el slash-command que la sustituye) con cada skill que la ruta exige, y si
falta alguno bloquea la edición (exit 2) diciendo cuál cargar.

Es best-effort al revés que un control de CI: si no puede leer el transcript
o algo falla, deja pasar. Un hook roto no puede bloquear el trabajo.
"""

import io
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]

CODIGO = (".py", ".ts", ".tsx")
# Árboles que no son código del repo aunque contengan .py/.ts.
AJENOS = (
    ".venv/",
    "node_modules/",
    ".claude/skills/",
    ".agents/skills/",
    ".github/skills/",
    ".opencode/skills/",
    "graphify-out/",
)
_COMANDO = re.compile(r"<command-name>/?([\w:.-]+)</command-name>")


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


def skills_exigidos(rel: str) -> list[tuple[str, str]]:
    """(skill, motivo) que exige editar `rel`, ruta relativa al checkout en POSIX."""
    if any(rel.startswith(a) or f"/{a}" in rel for a in AJENOS):
        return []
    exigidos: list[tuple[str, str]] = []
    if rel.endswith(CODIGO):
        exigidos.append(("ponytail", "es un cambio de código"))
    if rel.startswith("web/src/"):
        exigidos.append(("impeccable", "es interfaz en web/src/"))
    if rel.startswith("db/alembic/"):
        exigidos.append(
            (
                "sqlalchemy-alembic-expert-best-practices-code-review",
                "es una migración de db/alembic/",
            )
        )
    elif rel.startswith("db/") and rel.endswith(".py"):
        exigidos.append(("supabase-postgres-best-practices", "es SQL/persistencia en db/"))
    if rel.startswith("api/"):
        exigidos.append(("fastapi-python", "es la capa HTTP en api/"))
    if rel.startswith("tests/"):
        exigidos.append(("python-testing-patterns", "es un test en tests/"))
    return exigidos


def skills_cargados(transcript: pathlib.Path) -> set[str]:
    """Nombres de skill invocados en la sesión, sin el prefijo de plugin."""
    cargados: set[str] = set()
    with transcript.open(encoding="utf-8", errors="replace") as fichero:
        for linea in fichero:
            if "Skill" not in linea and "command-name" not in linea:
                continue
            try:
                contenido = json.loads(linea).get("message", {}).get("content")
            except (ValueError, AttributeError):
                continue
            bloques = contenido if isinstance(contenido, list) else [contenido]
            for bloque in bloques:
                if isinstance(bloque, str):
                    cargados.update(_COMANDO.findall(bloque))
                elif isinstance(bloque, dict):
                    if bloque.get("type") == "tool_use" and bloque.get("name") == "Skill":
                        cargados.add(str((bloque.get("input") or {}).get("skill", "")))
                    elif isinstance(bloque.get("text"), str):
                        cargados.update(_COMANDO.findall(bloque["text"]))
    return {nombre.rsplit(":", 1)[-1] for nombre in cargados if nombre}


def main() -> None:
    try:
        d = json.load(sys.stdin)
        fp = str((d.get("tool_input") or {}).get("file_path") or "")
        cwd = str(d.get("cwd") or "")
        transcript = pathlib.Path(str(d.get("transcript_path") or ""))
        if not fp or not transcript.is_file():
            return
        ruta = pathlib.Path(fp)
        if not ruta.is_absolute():
            ruta = pathlib.Path(cwd) / ruta
        try:
            rel = ruta.relative_to(raiz_del_checkout(str(ruta), cwd)).as_posix()
        except ValueError:
            return  # fuera del repo: scratchpad, memoria
        exigidos = skills_exigidos(rel)
        if not exigidos:
            return
        cargados = skills_cargados(transcript)
    except Exception:
        return
    faltan = [(skill, motivo) for skill, motivo in exigidos if skill not in cargados]
    if not faltan:
        return
    lineas = "\n".join(f"- `{skill}`: {motivo}." for skill, motivo in faltan)
    if isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr.reconfigure(encoding="utf-8")  # en Windows sería cp1252 y rompe los acentos
    print(
        f"Edición bloqueada: `{rel}` exige cargar antes estos skills con la "
        f"herramienta Skill (CLAUDE.md, sección Skills):\n{lineas}\n"
        "Cargalos, aplicá sus reglas al cambio y reintentá la edición. Seguir "
        "sus reglas de memoria no sustituye cargarlos.",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
