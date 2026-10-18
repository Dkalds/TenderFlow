"""Genera el índice de ADR en ``docs/adr/README.md``.

Mismo problema que resolvió ``gen_rfc_index.py`` para los RFC: treinta y tantos
ADR en un directorio sin índice. Para saber cuál sigue vigente había que abrirlos
uno a uno, y los once más recientes (ADR-026 a ADR-036) ni siquiera llevaban
frontmatter: su estado vivía en una viñeta del cuerpo, invisible para cualquier
herramienta que lea propiedades (el panel de Obsidian, Bases, Dataview, este
script).

El estado de un ADR pasa a ser **dato**: se lee del frontmatter y se valida
contra un vocabulario cerrado. Falla el ADR sin frontmatter, sin ``id`` o sin
``status`` válido, y el ``superseded`` que no dice por cuál: un ADR sustituido
sin destino deja al lector en un callejón.

Las referencias entre ADR del frontmatter (``supersedes``, ``superseded_by``,
``superseded_parcialmente_por``) admiten el id suelto (``ADR-016``) o el
wikilink a la nota (``"[[ADR-016-destino-persistencia-supabase]]"``), que es lo
que Obsidian convierte en link dentro de una propiedad. La tabla se escribe con
links markdown: es cuerpo, y en el cuerpo GitHub no renderiza wikilinks.

Uso::

    python scripts/gen_adr_index.py           # reescribe el índice
    python scripts/gen_adr_index.py --check   # falla si está desfasado
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ADR_DIR = _REPO_ROOT / "docs" / "adr"
_INDEX = _ADR_DIR / "README.md"

_BEGIN = "<!-- BEGIN indice-adr (generado por scripts/gen_adr_index.py — no editar a mano) -->"
_END = "<!-- END indice-adr -->"

#: Vocabulario cerrado del ``status`` de un ADR.
ESTADOS = {
    "proposed": "Propuesto; todavía no rige.",
    "accepted": "Vigente.",
    "rejected": "Se evaluó y se descartó.",
    "superseded": "Sustituido por otro ADR (`superseded_by`).",
}

_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---", re.S)
_ID = re.compile(r"ADR-(\d+)")


@dataclass(frozen=True, slots=True)
class Adr:
    fichero: str
    #: Tal como lo escribe el ADR (`ADR-0011` conserva sus cuatro dígitos).
    id: str
    #: El id normalizado a tres dígitos, con el que lo citan los demás.
    clave: str
    numero: int
    titulo: str
    status: str
    fecha: str
    #: Ids de los ADR que lo sustituyen, del todo o en parte.
    sustituido_por: tuple[str, ...]
    sustituido_parcialmente_por: tuple[str, ...]


def _campo(frontmatter: str, nombre: str) -> str:
    m = re.search(rf"^{nombre}:[ \t]*(.*)$", frontmatter, re.M)
    if not m:
        return ""
    return m.group(1).strip().strip('"').strip("'")


def _referencias(frontmatter: str, nombre: str) -> tuple[str, ...]:
    """Los ids que cita una clave, sea un valor suelto o una lista YAML."""
    m = re.search(rf"^{nombre}:[ \t]*(.*)$", frontmatter, re.M)
    if not m:
        return ()
    valor = m.group(1)
    for linea in frontmatter[m.end() :].splitlines()[1:]:
        if linea.strip() and not linea.startswith((" ", "\t")):
            break
        valor += " " + linea
    return tuple(f"ADR-{int(n):03d}" for n in _ID.findall(valor))


def leer_adrs() -> tuple[list[Adr], list[str]]:
    """Devuelve ``(adrs, errores)``."""
    adrs: list[Adr] = []
    errores: list[str] = []
    for fichero in sorted(_ADR_DIR.glob("*.md")):
        if fichero.name == "README.md":
            continue
        texto = fichero.read_text(encoding="utf-8")
        m = _FRONTMATTER.match(texto)
        if not m:
            errores.append(f"{fichero.name}: sin frontmatter YAML")
            continue
        frontmatter = m.group(1)
        adr_id = _campo(frontmatter, "id")
        m_id = _ID.fullmatch(adr_id)
        if not m_id:
            errores.append(f"{fichero.name}: sin `id: ADR-NNN`")
            continue
        numero = int(m_id.group(1))
        status = _campo(frontmatter, "status")
        if status not in ESTADOS:
            errores.append(
                f"{fichero.name}: `status: {status or '(vacío)'}` no está en el vocabulario "
                f"({', '.join(sorted(ESTADOS))})"
            )
            continue
        sustituido_por = _referencias(frontmatter, "superseded_by")
        if status == "superseded" and not sustituido_por:
            errores.append(f"{fichero.name}: `status: superseded` sin `superseded_by`")
            continue
        adrs.append(
            Adr(
                fichero=fichero.name,
                id=adr_id,
                clave=f"ADR-{numero:03d}",
                numero=numero,
                titulo=_campo(frontmatter, "title") or fichero.stem,
                status=status,
                fecha=_campo(frontmatter, "date"),
                sustituido_por=sustituido_por,
                sustituido_parcialmente_por=_referencias(
                    frontmatter, "superseded_parcialmente_por"
                ),
            )
        )

    vistos: dict[str, str] = {}
    for adr in adrs:
        if adr.clave in vistos:
            errores.append(
                f"{adr.fichero}: `id: {adr.id}` repetido (ya lo usa {vistos[adr.clave]})"
            )
        vistos[adr.clave] = adr.fichero
    for adr in adrs:
        for ref in (*adr.sustituido_por, *adr.sustituido_parcialmente_por):
            if ref not in vistos:
                errores.append(f"{adr.fichero}: cita {ref}, que no existe en docs/adr/")
    return adrs, errores


def render_block(adrs: list[Adr]) -> str:
    por_clave = {adr.clave: adr for adr in adrs}

    def enlace(ref: str) -> str:
        return f"[{por_clave[ref].id}]({por_clave[ref].fichero})"

    por_estado: dict[str, int] = {}
    for adr in adrs:
        por_estado[adr.status] = por_estado.get(adr.status, 0) + 1
    resumen = " · ".join(f"`{e}` {por_estado[e]}" for e in sorted(por_estado))
    cabecera = (
        f"**{len(adrs)} ADR**, de los cuales **{por_estado.get('accepted', 0)}** están "
        f"vigentes. {resumen}.\n\n"
        "Esta tabla se genera con `python scripts/gen_adr_index.py` a partir del "
        "frontmatter de cada ADR; CI la verifica con `--check`, igual que "
        "`make check-agent-docs` y la suite (`tests/test_unit_ratchet_indice_adr.py`). Un ADR "
        "sin `id` o `status` —o con un estado fuera del vocabulario— la hace fallar."
    )

    vocabulario = ["| Estado | Significado |", "|---|---|"]
    vocabulario += [f"| `{e}` | {d} |" for e, d in sorted(ESTADOS.items())]

    filas = ["| ADR | Título | Estado | Fecha | Sustituido por |", "|---|---|---|---|---|"]
    for adr in sorted(adrs, key=lambda a: a.numero):
        sustitutos = [enlace(r) for r in adr.sustituido_por]
        sustitutos += [f"{enlace(r)} (en parte)" for r in adr.sustituido_parcialmente_por]
        # Un `|` en el título partiría la celda.
        titulo = adr.titulo.replace("|", "\\|")
        filas.append(
            f"| [{adr.id}]({adr.fichero}) | {titulo} | `{adr.status}` | "
            f"{adr.fecha or '—'} | {', '.join(sustitutos) or '—'} |"
        )

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
    adrs, errores = leer_adrs()
    if errores:
        for e in errores:
            print(f"ERROR {e}", file=sys.stderr)
        print(f"\n{len(errores)} problema/s en el frontmatter de los ADR.", file=sys.stderr)
        return 1

    actual = _INDEX.read_text(encoding="utf-8")
    esperado = _reemplaza(actual, render_block(adrs))
    if actual == esperado:
        print(f"OK: el índice de {len(adrs)} ADR está al día.")
        return 0
    if check:
        print(
            f"ERROR: {_INDEX.relative_to(_REPO_ROOT)} tiene el índice desfasado.\n"
            f"Regenerá con: python scripts/gen_adr_index.py",
            file=sys.stderr,
        )
        return 1
    _INDEX.write_text(esperado, encoding="utf-8", newline="\n")
    print(f"Actualizado el índice de {len(adrs)} ADR en {_INDEX.relative_to(_REPO_ROOT)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
