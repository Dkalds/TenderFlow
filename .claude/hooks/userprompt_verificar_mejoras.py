"""UserPromptSubmit: si se piden mejoras o qué queda, recuerda verificar antes de proponer.

El 2026-11-07 un informe de mejoras propuso siete y cinco ya estaban hechas:
leyó solo el «Problema» de cada ítem del backlog, que se queda en el día en que
se abrió. La regla está en AGENTS.md §0 y en `/find-improvements`, pero una
pregunta suelta («¿qué mejorarías?») no pasa por el comando. Este hook la
inyecta como contexto cuando el mensaje pide mejoras, propuestas o lo que
queda pendiente. No bloquea nada.
"""

import json
import re
import sys

_PIDE_MEJORAS = re.compile(
    r"\bmejor(?:a|as|ar|arías|aria|arias)\b"
    r"|\bqu[eé] (?:queda|falta|harías|harias|propones|implementarías)\b"
    r"|\bpendientes?\b|\bbacklog\b|\bfind-improvements\b"
    r"|\b(?:improve|improves|improvement|improvements)\b",
    re.IGNORECASE,
)

#: Codex coloca este contexto después del mensaje del usuario, como mensaje de
#: developer, y un modelo puede tomarlo por la tarea (openai/codex#40680): por
#: eso empieza diciendo que no lo es.
AVISO = (
    "Nota sobre el mensaje del usuario de este turno, no una tarea nueva: responde a lo "
    "que pide. Antes de proponer o planificar mejoras (AGENTS.md §0), lee lo que queda con "
    "`make backlog-estado` (o `python scripts/check_backlog_freshness.py --estado`), "
    "no el «Problema» de cada ítem, que se queda en el día en que se abrió. Para cada "
    "propuesta, busca en el código el símbolo, fichero o setting que darías por ausente, "
    "y di si lo que queda es `código`, `propietario`, `medir` o `mixto`. Lo que solo puede hacer "
    "el dueño está en «Acciones del propietario» del backlog."
)


def main() -> int:
    try:
        datos = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    prompt = datos.get("prompt") if isinstance(datos, dict) else None
    if isinstance(prompt, str) and _PIDE_MEJORAS.search(prompt):
        # JSON en ASCII (`ó`): en Windows la salida va en la página de códigos
        # de la consola y los acentos llegaban rotos al modelo («petici�n»).
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": AVISO,
                    }
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
