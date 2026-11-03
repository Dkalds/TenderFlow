"""PreToolUse(Bash|Grep): el grafo de graphify antes que grep (AGENTS.md §1).

Con el CLI de graphify instalado, el grafo en el checkout y el transcript de la
sesión legible, la **primera** búsqueda de texto de la sesión se bloquea
(exit 2) hasta que se haya consultado el grafo (`graphify query`, `explain` o
`path`). Después, grep y rg quedan libres: siguen siendo lo correcto para un
literal. Hasta el 2026-11-03 esto era un aviso de una vez por sesión, y en la
sesión del PR #650 se ignoró de principio a fin con el grafo disponible.

Sin alguno de los tres (otro cliente, CLI sin instalar, sin grafo) queda el
aviso de antes: una vez por sesión y solo cuando el comando *empieza* una
búsqueda, no cuando `grep` filtra la salida de otro comando en una tubería.
"""

import io
import json
import pathlib
import re
import shutil
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


_CONSULTA_GRAFO = re.compile(r"\bgraphify\s+(query|path|explain)\b")


def grafo_consultado(transcript: pathlib.Path) -> bool | None:
    """¿Se ha consultado el grafo en la sesión? Por Bash o por una herramienta MCP de graphify.

    Solo mira las llamadas a herramientas (bloques ``tool_use`` del transcript de
    Claude Code), no el texto: este mismo hook y CLAUDE.md citan «graphify
    query», y contarlos daría por consultado lo que no se consultó. ``None`` si
    el transcript no tiene ninguna llamada con esa forma (otro cliente, como
    Codex): sin saber leerlo, no se bloquea.
    """
    reconocido = False
    with transcript.open(encoding="utf-8", errors="replace") as fichero:
        for linea in fichero:
            if "tool_use" not in linea:
                continue
            try:
                contenido = json.loads(linea).get("message", {}).get("content")
            except (ValueError, AttributeError):
                continue
            for bloque in contenido if isinstance(contenido, list) else []:
                if not isinstance(bloque, dict) or bloque.get("type") != "tool_use":
                    continue
                reconocido = True
                if "graphify" in str(bloque.get("name") or ""):
                    return True
                comando = str((bloque.get("input") or {}).get("command") or "")
                if _CONSULTA_GRAFO.search(comando):
                    return True
    return False if reconocido else None


BLOQUEO = (
    "Búsqueda bloqueada: este checkout tiene el grafo de graphify y en esta sesión "
    "todavía no se ha consultado (AGENTS.md §1, «graphify-first»). Antes de buscar en "
    'el código, pregúntale al grafo: `graphify query "<pregunta>"`, '
    "`graphify explain <símbolo>` o `graphify path <A> <B>`. Tras esa primera "
    "consulta, grep y rg quedan libres para literales y detalles."
)


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


def es_busqueda(d: dict[str, object]) -> bool:
    """La herramienta Grep siempre busca; en Bash, si el comando empieza una búsqueda."""
    if d.get("tool_name") == "Grep":
        return True
    entrada = d.get("tool_input") or d
    return isinstance(entrada, dict) and empieza_una_busqueda(str(entrada.get("command", "")))


def hay_que_bloquear(raiz: pathlib.Path, transcript: str) -> bool:
    """Grafo y CLI disponibles, transcript legible y sin consultar el grafo todavía."""
    ruta = pathlib.Path(transcript) if transcript else None
    if ruta is None or not ruta.is_file():
        return False
    if not (raiz / "graphify-out/graph.json").is_file() or shutil.which("graphify") is None:
        return False
    return grafo_consultado(ruta) is False


try:
    d = json.load(sys.stdin)
    session_id = str(d.get("session_id") or "")
    cwd = str(d.get("cwd") or "")
    transcript = str(d.get("transcript_path") or "")
    busca = es_busqueda(d)
except Exception:
    busca = False
    session_id = ""
    cwd = ""
    transcript = ""

bloquear = False
try:
    bloquear = busca and hay_que_bloquear(raiz_del_checkout(cwd), transcript)
except Exception:
    bloquear = False  # un hook roto no bloquea el trabajo
if bloquear:
    if isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr.reconfigure(encoding="utf-8")  # cp1252 en Windows rompe los acentos
    print(BLOQUEO, file=sys.stderr)
    sys.exit(2)

try:
    if busca and not ya_avisado(session_id):
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
