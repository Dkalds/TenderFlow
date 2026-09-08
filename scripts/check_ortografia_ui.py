"""Ortografía castellana de las cadenas visibles del frontend (C7.8).

Qué mide, y por qué no lo que parece
------------------------------------
El ítem pide «cero coincidencias de la lista en `web/src`». Un grep sobre el
fichero entero no vale: en este repo `"tecnologia"`, `"organo"` y `"licitacion"`
sin tilde son **nombres de campo de la API** y de los parámetros de filtro, y
acentuarlos rompería las peticiones. Lo que se lee en pantalla es otra cosa.

Por eso este control mira solo dos sitios:

1. **Texto JSX visible** (`>…<`).
2. **Props que renderizan copy**: `label`, `placeholder`, `aria-label`,
   `description`, `title`.

Un identificador, una clave de ordenación o un parámetro de query quedan fuera
por construcción, no por una allowlist que alguien tenga que mantener.

Estado medido el 2026-09-07
---------------------------
**Cero coincidencias**, y también cero `...` ASCII donde corresponde `…`. La ola
anterior (plan de septiembre) cerró el barrido; el ítem C7.8 lo daba por
pendiente porque el backlog no se había actualizado. Este script existe para que
siga cerrado: sin él, la siguiente pantalla nueva vuelve a introducir
«Ultimos 30 dias» y nadie se entera hasta que un cliente lo lee.

Uso::

    python scripts/check_ortografia_ui.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEB_SRC = _REPO_ROOT / "web" / "src"

#: Palabras castellanas que en la UI van con tilde.
#:
#: **Los plurales en `-ciones`/`-siones` NO están, y no es un olvido**: la tilde
#: de «licitación» existe porque la palabra es aguda acabada en -n; al pasar a
#: «licitaciones» el acento deja de ir en la última sílaba y la tilde desaparece.
#: Meterlos en la lista convertiría este control en una fábrica de faltas —el
#: primer borrador de este script daba 38 hallazgos y **los 38 eran correctos**—.
#: Los plurales que sí conservan tilde («órganos», «códigos», «tecnologías») son
#: los de palabras esdrújulas o con hiato, y esos sí están.
#:
#: `periodo` tampoco está: la RAE admite «periodo» y «período», así que exigir
#: una de las dos sería inventarse una regla.
PALABRAS_SIN_TILDE = (
    # -ción / -sión en singular: agudas acabadas en -n.
    "prediccion",
    "informacion",
    "configuracion",
    "descripcion",
    "aplicacion",
    "licitacion",
    "adjudicacion",
    "publicacion",
    "gestion",
    "sesion",
    # Esdrújulas y hiatos: la tilde se conserva en plural.
    "analisis",
    "busqueda",
    "busquedas",
    "ultimo",
    "ultima",
    "ultimos",
    "ultimas",
    "organo",
    "organos",
    "codigo",
    "codigos",
    "numero",
    "numeros",
    "categoria",
    "categorias",
    "tecnologia",
    "tecnologias",
    "dias",
    "exito",
    "exitos",
    "minimo",
    "minimos",
    "maximo",
    "maximos",
    "proximo",
    "proxima",
    "rapido",
    # Monosílabos y adverbios con tilde diacrítica o prosódica.
    "aqui",
    "segun",
    "tambien",
    "estan",
)

_RE_PALABRA = re.compile(
    r"\b(" + "|".join(PALABRAS_SIN_TILDE) + r")\b",
    re.IGNORECASE,
)

#: Texto entre etiquetas JSX. Excluye `{expresiones}`: ahí no hay copy literal.
_JSX_TEXT = re.compile(r">([^<>{}\n]{2,300})<")

#: Props que renderizan copy visible o accesible.
_UI_PROP = re.compile(
    r'\b(label|placeholder|aria-label|description|title)="([^"\n]{2,300})"',
)

#: `...` donde corresponde `…`. Solo en texto visible, no en código.
_ELIPSIS = "..."


def _es_test(ruta: Path) -> bool:
    return "__tests__" in ruta.as_posix() or ruta.name.endswith((".test.tsx", ".spec.tsx"))


def _fragmentos_visibles(texto: str) -> list[tuple[int, str]]:
    """`(offset, fragmento)` de todo lo que el usuario llega a leer."""
    encontrados: list[tuple[int, str]] = []
    for m in _JSX_TEXT.finditer(texto):
        encontrados.append((m.start(), m.group(1).strip()))
    for m in _UI_PROP.finditer(texto):
        encontrados.append((m.start(), m.group(2).strip()))
    return encontrados


def revisar() -> list[str]:
    """Hallazgos, uno por línea con su ruta y motivo."""
    hallazgos: list[str] = []
    for fichero in sorted(_WEB_SRC.rglob("*.tsx")):
        if _es_test(fichero):
            continue
        texto = fichero.read_text(encoding="utf-8")
        rel = fichero.relative_to(_REPO_ROOT).as_posix()
        for offset, fragmento in _fragmentos_visibles(texto):
            linea = texto[:offset].count("\n") + 1
            palabra = _RE_PALABRA.search(fragmento)
            if palabra:
                hallazgos.append(
                    f"{rel}:{linea}: «{palabra.group(0)}» sin tilde — {fragmento[:70]}"
                )
            if _ELIPSIS in fragmento:
                hallazgos.append(f"{rel}:{linea}: `...` donde va `…` — {fragmento[:70]}")
    return hallazgos


def main() -> int:
    hallazgos = revisar()
    for h in hallazgos:
        print(h, file=sys.stderr)
    print(f"Ortografía de la UI: {len(hallazgos)} hallazgo/s (objetivo 0).")
    return 1 if hallazgos else 0


if __name__ == "__main__":
    raise SystemExit(main())
