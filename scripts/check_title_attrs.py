"""Ratchet de `title=` nativo en JSX (C7.4).

Por qué existe
-------------
El atributo ``title`` de HTML es un tooltip que **no** existe para el teclado ni
para el táctil: no se puede enfocar, no se puede abrir sin ratón, los lectores
de pantalla lo anuncian de forma inconsistente y no se puede leer en un móvil.
Cuando lleva la única copia de un dato —el nombre completo de un órgano
truncado, la fecha exacta detrás de un «hace 3 días»— ese dato no existe para
quien no usa ratón.

`components/ui/tooltip.tsx` (Radix) sí es accesible, y es a donde tienen que ir.

La cifra del plan estaba mal, y por qué
---------------------------------------
El plan complementario cuenta **152 apariciones de `title=` en `.tsx`** y pide
bajarlas «por olas de ≥ 50». Ese grep cuenta tres cosas distintas:

1. `title` como **prop de un componente propio** (`<KpiCard title="…">`,
   `<EmptyState title="…">`): no genera atributo HTML y no tiene nada que ver
   con accesibilidad. Es la mayoría.
2. `title=` dentro de **tests**, que no llegan al navegador.
3. `title=` sobre un **elemento nativo**, que es el único caso del problema.

Medido el 2026-09-07 sobre `web/src`, excluyendo tests: **33 en 18 ficheros**.
La regla ESLint hermana (`eslint.config.mjs`, `no-restricted-syntax`) prohíbe
exactamente ese tercer caso salvo en `<abbr>` e `<iframe>`, donde el atributo es
semántico y no un tooltip.

O sea que no hay olas de cincuenta que hacer: hay 33 sitios, y este contador
impide que vuelvan a crecer mientras se migran.

Uso::

    python scripts/check_title_attrs.py
    python scripts/check_title_attrs.py --listar
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEB_SRC = _REPO_ROOT / "web" / "src"

#: `<tag ... title=`. La etiqueta en minúscula es lo que distingue un elemento
#: nativo de un componente de React, que por convención va en PascalCase — la
#: misma regla que usa el propio JSX para decidir si emite un tag o llama a una
#: función, así que no es una heurística: es la semántica del lenguaje.
_TITLE_NATIVO = re.compile(r"<([a-z][a-zA-Z0-9]*)\b[^>]*?\btitle=", re.DOTALL)

#: Donde `title` **no** es un tooltip sino semántica del elemento: la expansión
#: de una abreviatura y el nombre accesible de un marco embebido.
_EXENTOS = frozenset({"abbr", "iframe"})

#: Techo vigente. Medido el 2026-09-07. **Solo puede bajar.**
MAX_TITLE_NATIVO = 33


def _es_test(ruta: Path) -> bool:
    return "__tests__" in ruta.as_posix() or ruta.name.endswith((".test.tsx", ".spec.tsx"))


def contar() -> dict[str, int]:
    """`{ruta relativa: ocurrencias}` de los ficheros con `title=` nativo."""
    conteo: dict[str, int] = {}
    for fichero in sorted(_WEB_SRC.rglob("*.tsx")):
        if _es_test(fichero):
            continue
        etiquetas = [
            m.group(1)
            for m in _TITLE_NATIVO.finditer(fichero.read_text(encoding="utf-8"))
            if m.group(1) not in _EXENTOS
        ]
        if etiquetas:
            conteo[fichero.relative_to(_REPO_ROOT).as_posix()] = len(etiquetas)
    return conteo


def main(argv: list[str]) -> int:
    conteo = contar()
    total = sum(conteo.values())
    if "--listar" in argv:
        for ruta, n in sorted(conteo.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"{n:4d}  {ruta}")
    print(f"`title=` nativo en JSX: {total} en {len(conteo)} ficheros (techo {MAX_TITLE_NATIVO}).")
    if total > MAX_TITLE_NATIVO:
        print(
            f"ERROR: {total - MAX_TITLE_NATIVO} `title=` nativo/s nuevo/s. "
            "Usá `components/ui/tooltip.tsx`: el atributo nativo no existe para "
            "teclado ni táctil, así que el dato que lleva desaparece para quien "
            "no usa ratón.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
