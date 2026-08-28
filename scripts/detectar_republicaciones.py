#!/usr/bin/env python3
"""Encola a revisión las reemisiones del mismo contrato dentro de una fuente.

``services.dedupe.detect_duplicates`` se engancha en ``_post_ingestion`` del
runner de conectores y empareja fuentes **distintas**. La detección de
reemisiones intra-fuente (:func:`services.dedupe.detect_republicaciones`) no
tiene ese enganche a propósito: su primera pasada sobre una fuente sin cursor
evalúa la fuente entera y puede encolar decenas de miles de revisiones, y eso
no debe ocurrir como efecto colateral silencioso de una ingesta nocturna.

Que este job no haya corrido **no** deja duplicados en la superficie pública:
``db/repositories/publico.py`` colapsa las reemisiones en la propia consulta,
sin depender de ninguna marca. Este script sirve para lo otro —que las métricas
competitivas dejen de contar dos veces el mismo contrato— y para eso hace falta
que un humano confirme cada par: todo lo que marca entra como ``pending``, que
no excluye nada de ninguna métrica hasta pasar por
``services.dedupe.resolve_pending``. En otras palabras, ejecutarlo es
reversible; no hace falta un ``--dry-run`` que fingiera serlo más.

Uso::

    python scripts/detectar_republicaciones.py --fuente pscp
    python scripts/detectar_republicaciones.py --fuente ted --detalles 50
"""

from __future__ import annotations

import argparse
import sys

from services.dedupe import detect_republicaciones

#: Fuentes con ``id_externo`` por anuncio y no por contrato. No es validación
#: cerrada —``--fuente`` acepta cualquier valor— sino la lista de las que se
#: sabe que reemiten; se avisa cuando alguien pasa otra cosa, por si es un typo.
_FUENTES_CONOCIDAS = ("pscp", "ted")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fuente", required=True, help=f"p.ej. {', '.join(_FUENTES_CONOCIDAS)}")
    p.add_argument("--detalles", type=int, default=20, help="Cuántos pares imprimir")
    args = p.parse_args()

    if args.fuente not in _FUENTES_CONOCIDAS:
        print(
            f"Aviso: '{args.fuente}' no está entre las fuentes que se sabe que "
            f"reemiten ({', '.join(_FUENTES_CONOCIDAS)}). Sigo igualmente.",
            file=sys.stderr,
        )

    resultado = detect_republicaciones(fuente=args.fuente)
    print(
        f"fuente={resultado.fuente} evaluadas={resultado.evaluadas} "
        f"pendientes_de_revision={resultado.pendientes}"
    )
    tope = max(0, args.detalles)
    for detalle in resultado.detalles[:tope]:
        print(f"  {detalle['duplicada']}  →reemisión de→  {detalle['canonica']}")
    if len(resultado.detalles) > tope:
        print(f"  ... y {len(resultado.detalles) - tope} más")
    if resultado.pendientes:
        print("Cola de revisión: services.dedupe.review_pending()")
    return 0


if __name__ == "__main__":
    sys.exit(main())
