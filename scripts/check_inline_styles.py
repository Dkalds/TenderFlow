"""Ratchet de estilos inline en JSX — el bloqueo real de C2.8.

El ítem pide quitar ``'unsafe-inline'`` de ``style-src`` con nonce o hash para
los estilos que Tailwind 4 emite en runtime. Al medirlo aparece que ese no es el
bloqueo:

- Un **nonce sí cubre** los ``<style>`` que Tailwind inyecta.
- Un nonce **no cubre los atributos** ``style={{...}}``, que son 94 en 33
  ficheros (medido el 2026-09-06). Para esos haría falta ``'unsafe-hashes'``
  más un hash **por valor**, y 12 de ellos son valores calculados
  (``width: `${pct}%```): su hash cambia en cada render, así que no hay lista de
  hashes posible.
- `recharts` (18 ficheros) genera además estilos propios al pintar los SVG, sin
  punto de enganche donde poner un nonce.

Y hay un detalle que hace la corrección parcial **peor que no tocar nada**: en
CSP nivel 3, en cuanto ``style-src`` lleva un nonce o un hash, el navegador
**ignora** ``'unsafe-inline'``. O sea que añadir el nonce sin haber migrado los
94 atributos no endurece la política: rompe la página.

Por eso este control no cambia la cabecera. Cuenta, y el número **solo puede
bajar**. Cuando llegue a cero, quitar ``'unsafe-inline'`` de
``web/src/proxy.ts`` es una línea.

Uso::

    python scripts/check_inline_styles.py
    python scripts/check_inline_styles.py --listar
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEB_SRC = _REPO_ROOT / "web" / "src"

#: Atributos `style={{...}}` en JSX. No cuenta `<style>` (elemento), que un
#: nonce sí puede cubrir y no es lo que bloquea el endurecimiento.
_STYLE_ATTR = re.compile(r"style=\{\{")

#: Techo vigente. Medido el 2026-09-06. **Solo puede bajar.**
#:
#: Bajarlo es el trabajo que desbloquea C2.8; subirlo es declarar que se acepta
#: seguir con `'unsafe-inline'` en `style-src`, y eso no se hace de pasada.
MAX_ESTILOS_INLINE = 94


def contar() -> dict[str, int]:
    """`{ruta relativa: ocurrencias}` de los ficheros con estilos inline."""
    conteo: dict[str, int] = {}
    for fichero in sorted(_WEB_SRC.rglob("*.tsx")):
        n = len(_STYLE_ATTR.findall(fichero.read_text(encoding="utf-8")))
        if n:
            conteo[fichero.relative_to(_REPO_ROOT).as_posix()] = n
    return conteo


def main() -> int:
    conteo = contar()
    total = sum(conteo.values())

    if "--listar" in sys.argv:
        for ruta, n in sorted(conteo.items(), key=lambda par: -par[1]):
            print(f"  {n:>3}  {ruta}")
        print()

    print(f"Estilos inline en JSX: {total} en {len(conteo)} ficheros (techo {MAX_ESTILOS_INLINE}).")

    if total > MAX_ESTILOS_INLINE:
        print(
            f"\nERROR: {total - MAX_ESTILOS_INLINE} estilo/s inline nuevo/s. "
            "Cada uno aleja el momento en que `style-src` puede dejar de llevar "
            "`'unsafe-inline'` (C2.8). Usá una clase de Tailwind o una variable "
            "CSS; si el valor es calculado, una custom property en el elemento.",
            file=sys.stderr,
        )
        return 1

    if total < MAX_ESTILOS_INLINE:
        print(f"\nEl techo se puede bajar a {total}: actualizá MAX_ESTILOS_INLINE en este script.")
        return 1

    if total == 0:
        print(
            "\nCero estilos inline: `web/src/proxy.ts` ya puede quitar "
            "`'unsafe-inline'` de `style-src` y poner el nonce."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
