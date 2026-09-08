"""Publica la política de retención en ``docs/SECURITY.md`` (C9.3).

Hasta 2026-09 los plazos vivían como literales en ``scheduler/retention.py`` y
en los ``--*-days`` del CLI, y no aparecían en ningún documento: ni en
``docs/SECURITY.md`` ni en los runbooks. Un plazo que solo existe en el código
no es una política de retención, es un detalle de implementación — y el RGPD
pide poder decir cuánto se conserva cada cosa y por qué.

La fuente es ``scheduler.retention.POLITICA_RETENCION``, que a su vez lee
``RETENTION_*`` de ``config/settings.py``. Este script no conoce ningún plazo.

Uso::

    python scripts/gen_retention_doc.py           # reescribe el bloque
    python scripts/gen_retention_doc.py --check   # falla si está desfasado
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_DOC = _REPO_ROOT / "docs" / "SECURITY.md"

_BEGIN = "<!-- BEGIN retencion (generado por scripts/gen_retention_doc.py — no editar a mano) -->"
_END = "<!-- END retencion -->"

# Comando que purga cada tabla. `rate_limits` no va por plazo sino por su propia
# columna de expiración, y por eso se nombra aparte en la tabla.
_COMANDO_GENERAL = "`python scripts/retention_cleanup.py --apply`"


def _humaniza(dias: int) -> str:
    if dias == 0:
        return "sin purga"
    if dias == 1:
        return "1 día"
    if dias % 365 == 0:
        anios = dias // 365
        return f"{dias} días ({anios} año{'s' if anios > 1 else ''})"
    if dias % 30 == 0:
        meses = dias // 30
        return f"{dias} días ({meses} mes{'es' if meses > 1 else ''})"
    return f"{dias} días"


def render_block() -> str:
    from scheduler.retention import POLITICA_RETENCION

    filas = [
        "| Tabla | Plazo | Motivo | Comando |",
        "|---|---|---|---|",
    ]
    for regla in POLITICA_RETENCION:
        comando = (
            "`python scripts/retention_cleanup.py --apply` (por `reset_at`, no por plazo)"
            if regla.tabla == "rate_limits"
            else _COMANDO_GENERAL
        )
        filas.append(f"| `{regla.tabla}` | {_humaniza(regla.dias)} | {regla.motivo} | {comando} |")

    cabecera = (
        "Los plazos son configuración (`RETENTION_*` en `config/settings.py`, documentados en\n"
        "`.env.example`) y la política vive en `scheduler/retention.py::POLITICA_RETENCION`.\n"
        "Esta tabla se genera con `python scripts/gen_retention_doc.py`; CI la verifica con\n"
        "`--check`, así que no puede quedarse atrás respecto del código que purga.\n\n"
        "El job programado `retention_cleanup` la aplica a diario. Las tablas\n"
        "`licitaciones` y `adjudicaciones` **no** se purgan: son el dato público que el\n"
        "producto existe para conservar."
    )
    return f"{_BEGIN}\n\n{cabecera}\n\n" + "\n".join(filas) + f"\n\n{_END}"


def _reemplaza(texto: str, bloque: str) -> str:
    inicio = texto.find(_BEGIN)
    fin = texto.find(_END)
    if inicio == -1 or fin == -1:
        raise SystemExit(
            f"{_DOC.relative_to(_REPO_ROOT)}: faltan los delimitadores del bloque de retención.\n"
            f"Añadí {_BEGIN!r} y {_END!r} donde deba ir la tabla."
        )
    return texto[:inicio] + bloque + texto[fin + len(_END) :]


def main() -> int:
    check = "--check" in sys.argv
    actual = _DOC.read_text(encoding="utf-8")
    esperado = _reemplaza(actual, render_block())

    if actual == esperado:
        print(f"OK: la política de retención de {_DOC.relative_to(_REPO_ROOT)} está al día.")
        return 0
    if check:
        print(
            f"ERROR: {_DOC.relative_to(_REPO_ROOT)} publica una política de retención "
            f"distinta de la que aplica el código.\n"
            f"Regenerá con: python scripts/gen_retention_doc.py",
            file=sys.stderr,
        )
        return 1
    _DOC.write_text(esperado, encoding="utf-8", newline="\n")
    print(f"Actualizada la política de retención en {_DOC.relative_to(_REPO_ROOT)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
