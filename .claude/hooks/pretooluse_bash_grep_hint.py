"""PreToolUse(Bash): recuerda que hay algo mejor que grep para navegar el código.

Avisa **una vez por sesión** y solo cuando el comando *empieza* una búsqueda.
Hasta 2026-10 saltaba en cada comando que contuviera «grep» o «find » en
cualquier parte —también como filtro de una tubería (`ls | grep x`) o dentro
de un `git ls-files | grep`—, así que el mismo párrafo entraba en el contexto
decenas de veces por sesión sin que hubiera nada que consultar en el grafo.
"""

import json
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]

SEARCH_TOOLS = {"grep", "egrep", "fgrep", "rg", "ripgrep", "find", "fd", "ack", "ag"}
# Separadores de comandos de shell. La tubería se trata aparte: lo que va
# detrás de `|` filtra la salida de otro comando, no busca en el repo.
_SEGMENTOS = re.compile(r"&&|\|\||;|\n")
_ASIGNACION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

CON_GRAFO = (
    "graphify: knowledge graph at graphify-out/. For focused questions, "
    'run `graphify query "<question>"` (or `path` / `explain`) before grepping raw files. '
    "Read GRAPH_REPORT.md only for broad architecture context."
)
SIN_GRAFO = (
    "No hay grafo de graphify en este checkout. Para «dónde se define X» o «quién "
    "importa Y» en Python, `python scripts/code_map.py simbolo <nombre>` / "
    "`importadores <módulo>` / `paquete <paquete>` responden desde el AST sin "
    "dependencias; para el resto, búsqueda de texto."
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


def empieza_una_busqueda(cmd: str) -> bool:
    """¿Algún comando de la línea, sin contar filtros de tubería, es una búsqueda?"""
    for segmento in _SEGMENTOS.split(cmd):
        origen = segmento.split("|", 1)[0]
        palabras = [p for p in origen.split() if not _ASIGNACION.match(p)]
        if not palabras:
            continue
        primera = palabras[0].rsplit("/", 1)[-1]
        if primera in SEARCH_TOOLS:
            return True
        if primera == "git" and len(palabras) > 1 and palabras[1] == "grep":
            return True
    return False


def ya_avisado(session_id: str) -> bool:
    """Marca la sesión como avisada; devuelve si ya lo estaba.

    Sin ``session_id`` (clientes que no lo mandan) no hay dónde recordar nada
    y el aviso sale siempre, como antes.
    """
    if not session_id:
        return False
    limpio = re.sub(r"[^A-Za-z0-9_-]", "", session_id)[:80]
    if not limpio:
        return False
    marca = pathlib.Path(tempfile.gettempdir()) / f"tf-pista-busqueda-{limpio}"
    if marca.exists():
        return True
    marca.touch()
    return False


try:
    d = json.load(sys.stdin)
    cmd = (d.get("tool_input") or d).get("command", "")
    session_id = str(d.get("session_id") or "")
    cwd = str(d.get("cwd") or "")
except Exception:
    cmd = ""
    session_id = ""
    cwd = ""

try:
    if empieza_una_busqueda(cmd) and not ya_avisado(session_id):
        raiz = raiz_del_checkout(cwd)
        hay_grafo = (raiz / "graphify-out/graph.json").is_file()
        hay_mapa = (raiz / "scripts/code_map.py").is_file()
        mensaje = CON_GRAFO if hay_grafo else SIN_GRAFO if hay_mapa else ""
        if mensaje:
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "additionalContext": mensaje,
                        }
                    }
                )
            )
except Exception:
    pass
