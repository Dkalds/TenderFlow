"""Genera el índice de RFC en ``docs/rfc/README.md`` (C9.6).

Setenta RFC en un directorio, sin índice, es un directorio: para saber cuáles
siguen abiertos había que abrirlos uno a uno. El resultado predecible es que
cinco RFC figuraban como abiertos estando implementados (hecho 25 del plan v2).

El estado de un RFC pasa a ser **dato**: se lee del frontmatter, se valida
contra un vocabulario cerrado, y se publica con enlace a la evidencia de
implementación cuando el RFC la declara.

Un RFC sin ``status``, o con un ``status`` fuera del vocabulario, **falla**: es
justo el caso que dejaba el estado sin responder.

Uso::

    python scripts/gen_rfc_index.py           # reescribe el índice
    python scripts/gen_rfc_index.py --check   # falla si está desfasado
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_RFC_DIR = _REPO_ROOT / "docs" / "rfc"
_INDEX = _RFC_DIR / "README.md"

_BEGIN = "<!-- BEGIN indice-rfc (generado por scripts/gen_rfc_index.py — no editar a mano) -->"
_END = "<!-- END indice-rfc -->"

#: Vocabulario cerrado. Coincide con la plantilla del propio README.
#:
#: `accepted` y `retired` no están: son sinónimos que se colaron y que el check
#: obliga a normalizar (`approved` y `obsolete` respectivamente). Un vocabulario
#: con sinónimos no permite contar cuántos RFC siguen abiertos.
ESTADOS = {
    "draft": "Borrador, sin acordar.",
    "review": "En revisión.",
    "approved": "Acordado; el código todavía no existe.",
    "rejected": "Descartado.",
    "implemented": "El código existe en el árbol.",
    "partially-implemented": "Parte del código existe; el RFC dice qué falta.",
    "superseded": "Sustituido por otro RFC o graduado a ADR.",
    "obsolete": "Ya no aplica (la arquitectura que describe no existe).",
}

#: Estados que cuentan como «cerrado» a efectos del resumen.
_CERRADOS = frozenset({"implemented", "rejected", "superseded", "obsolete"})

_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---", re.S)


@dataclass(frozen=True, slots=True)
class Rfc:
    fichero: str
    titulo: str
    status: str
    fecha: str
    #: Ruta o rutas donde vive el código que lo implementa, si el RFC lo declara
    #: en `evidence:`. El criterio es el de `docs/rfc/README.md`: implementado
    #: significa que el código existe, no que el PR se haya mergeado.
    evidencia: str


def _campo(frontmatter: str, nombre: str) -> str:
    m = re.search(rf"^{nombre}:\s*(.+)$", frontmatter, re.M)
    if not m:
        return ""
    return m.group(1).strip().strip('"').strip("'")


def leer_rfcs() -> tuple[list[Rfc], list[str]]:
    """Devuelve ``(rfcs, errores)``. Un RFC sin `status` válido es un error."""
    rfcs: list[Rfc] = []
    errores: list[str] = []
    for fichero in sorted(_RFC_DIR.glob("*.md")):
        if fichero.name == "README.md":
            continue
        texto = fichero.read_text(encoding="utf-8")
        m = _FRONTMATTER.match(texto)
        if not m:
            errores.append(f"{fichero.name}: sin frontmatter YAML")
            continue
        frontmatter = m.group(1)
        status = _campo(frontmatter, "status")
        if not status:
            errores.append(f"{fichero.name}: sin `status`")
            continue
        if status not in ESTADOS:
            errores.append(
                f"{fichero.name}: `status: {status}` no está en el vocabulario "
                f"({', '.join(sorted(ESTADOS))})"
            )
            continue
        titulo = _campo(frontmatter, "title") or fichero.stem
        rfcs.append(
            Rfc(
                fichero=fichero.name,
                titulo=titulo,
                status=status,
                fecha=_campo(frontmatter, "date"),
                evidencia=_campo(frontmatter, "evidence"),
            )
        )
    return rfcs, errores


def render_block(rfcs: list[Rfc]) -> str:
    por_estado: dict[str, int] = {}
    for rfc in rfcs:
        por_estado[rfc.status] = por_estado.get(rfc.status, 0) + 1
    abiertos = sum(n for e, n in por_estado.items() if e not in _CERRADOS)

    resumen = " · ".join(f"`{e}` {por_estado[e]}" for e in sorted(por_estado))
    cabecera = (
        f"**{len(rfcs)} RFC**, de los cuales **{abiertos}** siguen abiertos. {resumen}.\n\n"
        "**Criterio de `implemented`: que el código exista en el árbol, no que el PR se "
        "haya mergeado.** Un RFC cuyo código está pero cuyo PR quedó abierto está "
        "implementado; uno cuyo PR se mergeó sin dejar código, no.\n\n"
        "La columna «Evidencia» sale del campo `evidence:` del frontmatter del propio "
        "RFC. Un RFC `implemented` sin evidencia declarada no falla el check, pero "
        "obliga a quien lo lea a buscarla: declarala.\n\n"
        "Esta tabla se genera con `python scripts/gen_rfc_index.py`; CI la verifica con "
        "`--check`, y un RFC sin `status` —o con uno fuera del vocabulario— lo hace "
        "fallar."
    )

    filas = ["| RFC | Estado | Fecha | Evidencia |", "|---|---|---|---|"]
    for rfc in sorted(rfcs, key=lambda r: (r.status, r.fichero)):
        evidencia = rfc.evidencia or "—"
        filas.append(
            f"| [{rfc.titulo}]({rfc.fichero}) | `{rfc.status}` | {rfc.fecha or '—'} "
            f"| {evidencia} |"
        )

    vocabulario = ["| Estado | Significado |", "|---|---|"]
    vocabulario += [f"| `{e}` | {d} |" for e, d in sorted(ESTADOS.items())]

    return (
        f"{_BEGIN}\n\n{cabecera}\n\n"
        + "\n".join(vocabulario)
        + "\n\n"
        + "\n".join(filas)
        + f"\n\n{_END}"
    )


def _reemplaza(texto: str, bloque: str) -> str:
    inicio = texto.find(_BEGIN)
    fin = texto.find(_END)
    if inicio == -1 or fin == -1:
        raise SystemExit(
            f"{_INDEX.relative_to(_REPO_ROOT)}: faltan los delimitadores del índice.\n"
            f"Añadí {_BEGIN!r} y {_END!r} donde deba ir la tabla."
        )
    return texto[:inicio] + bloque + texto[fin + len(_END) :]


def main() -> int:
    check = "--check" in sys.argv
    rfcs, errores = leer_rfcs()
    if errores:
        for e in errores:
            print(f"ERROR {e}", file=sys.stderr)
        print(f"\n{len(errores)} RFC sin estado utilizable.", file=sys.stderr)
        return 1

    actual = _INDEX.read_text(encoding="utf-8")
    esperado = _reemplaza(actual, render_block(rfcs))
    if actual == esperado:
        print(f"OK: el índice de {len(rfcs)} RFC está al día.")
        return 0
    if check:
        print(
            f"ERROR: {_INDEX.relative_to(_REPO_ROOT)} tiene el índice desfasado.\n"
            f"Regenerá con: python scripts/gen_rfc_index.py",
            file=sys.stderr,
        )
        return 1
    _INDEX.write_text(esperado, encoding="utf-8", newline="\n")
    print(f"Actualizado el índice de {len(rfcs)} RFC en {_INDEX.relative_to(_REPO_ROOT)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
