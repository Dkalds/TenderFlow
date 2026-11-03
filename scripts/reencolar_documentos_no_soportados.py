"""Reencola los documentos sin soporte cuyo formato el extractor ya sabe leer (S8).

``unsupported`` es un estado terminal a propósito: nada lo revisa solo, porque
reintentarlo con el mismo extractor daría lo mismo y se comería el lote
nocturno. Cuando el extractor aprende un formato, las filas que se quedaron
atrás hay que devolverlas a ``pending`` a mano. Es lo que hace este script.

Medido en producción el 2026-10-23 (MCP de solo lectura): unas 2.100 filas de
DOCX con el content-type mal escrito de PLACSP (``…openxmlformatsofficedocument…``,
sin guion), 1.007 en ``unsupported`` y 1.131 en ``error`` con el detalle de
antes de ``v103``; 48 ODT y 2 ODS en ``error``/``unsupported``; y 215 ZIP. XLSX,
HTML, XML, RTF, ``.doc`` y RAR siguen sin leerse y no se tocan.

**Lo ejecuta el propietario contra producción** (dato de producción, AGENTS.md
§6): ver ``docs/runbooks/documentos-reencolar.md``. Por defecto solo cuenta::

    make reencolar-documentos                 # cuenta, no escribe
    make reencolar-documentos APLICAR=1       # reencola

    python scripts/reencolar_documentos_no_soportados.py [--aplicar] [--json]

Requiere ``DATABASE_URL``. Es idempotente: una segunda pasada no encuentra
nada que reencolar hasta que el lote nocturno vuelva a dejar alguna fila en
``unsupported``.

Con ``--sin-texto`` reencola en cambio los PDF escaneados (``sin_texto``) que
se leyeron antes de que el runner de ``pliegos.yml`` tuviera OCR
(:data:`OCR_EN_EL_RUNNER_DESDE`): nunca pasaron por ``ocrmypdf`` y la próxima
pasada se lo aplica. Medido el 2026-11-03: 51 de los 53 ``sin_texto``, ninguno
con binario guardado, así que se vuelven a descargar y los enlaces caducados
acabarán en ``error``. El log ``document_ocr_extracted`` de esa pasada trae
``segundos_por_pagina``, que es la medida que S8.3 pedía antes de ampliar::

    make reencolar-documentos SIN_TEXTO=1            # cuenta
    make reencolar-documentos SIN_TEXTO=1 APLICAR=1  # reencola
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from db.repositories.documentos import DocumentosRepository  # noqa: E402
from scraper.document_fetcher import supported_content_types  # noqa: E402

#: Día en que ``ocrmypdf`` entró en el runner de ``pliegos.yml`` (#274).
OCR_EN_EL_RUNNER_DESDE = "2026-09-08"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="Reencola de verdad. Sin esta opción solo se cuenta lo que se reencolaría.",
    )
    parser.add_argument(
        "--sin-texto",
        action="store_true",
        help="Reencola los PDF escaneados leídos antes de que el runner tuviera OCR.",
    )
    parser.add_argument("--json", action="store_true", help="Salida en JSON")
    args = parser.parse_args(argv)

    if args.sin_texto:
        total = DocumentosRepository().reencolar_sin_texto(
            antes_de=OCR_EN_EL_RUNNER_DESDE, aplicar=args.aplicar
        )
        if args.json:
            print(json.dumps({"aplicado": args.aplicar, "sin_texto": total}, indent=2))
            return 0
        verbo = "Reencolados" if args.aplicar else "Se reencolarían"
        print(f"{verbo} {total} PDF sin texto leídos antes del OCR ({OCR_EN_EL_RUNNER_DESDE}).")
        return 0

    tipos = sorted(supported_content_types())
    filas = DocumentosRepository().reencolar_formatos_soportados(tipos, aplicar=args.aplicar)
    total = sum(int(f["total"]) for f in filas)

    if args.json:
        print(json.dumps({"aplicado": args.aplicar, "total": total, "por_tipo": filas}, indent=2))
        return 0

    verbo = "Reencolados" if args.aplicar else "Se reencolarían"
    print(f"{verbo} {total} documentos (formatos soportados: {', '.join(tipos)})")
    for fila in filas:
        print(f"  {int(fila['total']):>6}  {fila['status']:<12} {fila['content_type']}")
    if not args.aplicar and total:
        print("Sin escribir nada. Repetí con --aplicar (make reencolar-documentos APLICAR=1).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
