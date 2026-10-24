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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="Reencola de verdad. Sin esta opción solo se cuenta lo que se reencolaría.",
    )
    parser.add_argument("--json", action="store_true", help="Salida en JSON")
    args = parser.parse_args(argv)

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
