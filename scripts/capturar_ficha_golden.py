"""Captura un pliego real como caso del golden de la ficha.

Por qué existe
--------------
El eval de la ficha (``docs/plans/2026-10-eval-ficha-pliego.md``) mide la
extracción contra pliegos reales con etiquetas humanas. Este script trae de la
base lo que hace falta para etiquetar uno: **todas** sus páginas de texto —el
selector de páginas es parte de lo que se evalúa— y la ficha vigente como
propuesta, con cada hecho sin veredicto.

Solo lee. Necesita la base donde están los pliegos (producción), así que lo
ejecuta quien tiene esa ``DATABASE_URL``.

Uso
---
Ver los candidatos, para elegir con los criterios de la especificación (§3:
las tres fuentes, un multi-lote, uno con fórmula de precio, uno con OCR, uno
corto y uno largo, y dos cuya ficha sea pobre o ``failed``)::

    python scripts/capturar_ficha_golden.py --listar

Capturar uno (``--completo`` en los tres que se van a leer a fondo)::

    python scripts/capturar_ficha_golden.py <licitacion_id> --caso <nombre> [--completo]

Después, ``scripts/revisar_ficha_golden.py <nombre>``.

Lo que no hace
--------------
No pisa un caso que ya existe: recapturar uno revisado borraría el etiquetado.
``--forzar`` lo permite a sabiendas. Y no guarda la ``uri`` del documento: las
de PLACSP llevan un token.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any

_RAIZ_REPO = Path(__file__).resolve().parent.parent
if str(_RAIZ_REPO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_REPO))

from db.repositories.documentos import DocumentosRepository  # noqa: E402
from db.repositories.tender_fact_sheets import TenderFactSheetsRepository  # noqa: E402
from services.rag.ficha_golden import (  # noqa: E402
    NOMBRE_GOLDEN,
    escribir_golden,
    escribir_paginas,
    propuesta_desde_ficha,
    sin_revisar,
)

RAIZ_POR_DEFECTO = _RAIZ_REPO / "tests" / "eval" / "fixtures" / "fichas"

#: A partir de aquí la captura avisa: el texto de los pliegos se versiona, y un
#: caso enorme merece que alguien lo decida en vez de que entre sin más.
AVISO_TAMANO_BYTES = 1_000_000


class CasoYaExiste(Exception):
    """La carpeta ya tiene un ``golden.json`` y no se pidió ``--forzar``."""


def capturar(
    licitacion_id: str,
    carpeta: Path,
    *,
    completo: bool,
    forzar: bool,
    documentos: Any,
    fichas: Any,
    hoy: date,
) -> int:
    """Escribe el caso en ``carpeta`` y devuelve los bytes de ``paginas.jsonl``."""
    if (carpeta / NOMBRE_GOLDEN).exists() and not forzar:
        raise CasoYaExiste(str(carpeta))
    paginas = documentos.list_pages_by_licitacion(licitacion_id)
    if not any(str(p.get("texto") or "").strip() for p in paginas):
        raise ValueError(f"{licitacion_id} no tiene páginas de texto: no hay nada que etiquetar")
    golden = propuesta_desde_ficha(
        licitacion_id, fichas.get(licitacion_id), completo=completo, hoy=hoy
    )
    escritos = escribir_paginas(carpeta, paginas)
    escribir_golden(carpeta, golden)
    return escritos


def _listar(fichas: Any) -> None:
    filas = fichas.list_candidatas_golden()
    print(
        f"{'licitacion_id':40} {'fuente':8} {'docs':>4} {'págs':>5} {'ocr':>4} "
        f"{'estado':13} {'hechos':>6} {'lotes':>5} {'fórm.':>5}  versión"
    )
    for fila in filas:
        hechos = fila.get("field_count")
        print(
            f"{str(fila['licitacion_id'])[:40]:40} {str(fila.get('fuente') or '—')[:8]:8} "
            f"{fila.get('documentos') or 0:>4} {fila.get('paginas') or 0:>5} "
            f"{fila.get('paginas_ocr') or 0:>4} {fila.get('status') or 'sin ficha'!s:13} "
            f"{'—' if hechos is None else hechos:>6} {fila.get('lotes') or 0:>5} "
            f"{fila.get('formulas') or 0:>5}  {fila.get('extraction_version') or '—'}"
        )
    print(f"\n{len(filas)} expedientes con texto de pliego.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Captura un pliego real como caso del golden de la ficha."
    )
    parser.add_argument("licitacion_id", nargs="?", help="id_externo del expediente")
    parser.add_argument("--listar", action="store_true", help="ver los candidatos y salir")
    parser.add_argument("--caso", help="nombre de la carpeta del caso")
    parser.add_argument(
        "--completo",
        action="store_true",
        help="el caso se va a leer a fondo para añadir lo que la ficha omite",
    )
    parser.add_argument(
        "--forzar", action="store_true", help="reescribir un caso que ya existe (borra su revisión)"
    )
    parser.add_argument("--raiz", type=Path, default=RAIZ_POR_DEFECTO)
    args = parser.parse_args(argv)

    fichas = TenderFactSheetsRepository()
    if args.listar:
        _listar(fichas)
        return 0

    if not args.licitacion_id or not args.caso:
        print("Hacen falta el id del expediente y --caso <nombre> (o --listar).", file=sys.stderr)
        return 2

    carpeta = args.raiz / args.caso
    try:
        escritos = capturar(
            args.licitacion_id,
            carpeta,
            completo=args.completo,
            forzar=args.forzar,
            documentos=DocumentosRepository(),
            fichas=fichas,
            hoy=date.today(),
        )
    except CasoYaExiste:
        print(
            f"El caso {carpeta} ya existe y recapturarlo borraría su revisión. "
            "Si es lo que quieres, repite con --forzar.",
            file=sys.stderr,
        )
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    from services.rag.ficha_golden import leer_caso

    caso = leer_caso(carpeta)
    print(
        f"Caso {args.caso}: {len(caso.paginas)} páginas ({escritos / 1024:.0f} KB), "
        f"{sin_revisar(caso.golden)} hechos por revisar"
        f"{' · completo' if caso.golden.completo else ''}."
    )
    if escritos > AVISO_TAMANO_BYTES:
        print(
            f"Aviso: las páginas de este caso pasan de 1 MB ({escritos / 1_000_000:.1f} MB). "
            "Se versionan con el repositorio: comprueba que el caso lo merece.",
            file=sys.stderr,
        )
    print(f"Siguiente paso: python scripts/revisar_ficha_golden.py {args.caso}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
