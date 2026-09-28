"""Exporta el golden set real de «¿es TI?» desde la revisión humana (F2).

Por qué existe
---------------
``tests/fixtures/golden_ti.jsonl`` (``services.ml.golden_ti``) es el gate real
del binario ``es_ti`` del plan de clasificación en tres niveles, y a
diferencia del golden set legacy (``golden_set.jsonl``, escrito a mano) no se
edita a mano: sale íntegro de la revisión humana ya guardada en
``ml_feedback`` (``source='revision_ti'``, ver
``db.repositories.feedback.FUENTE_REVISION_TI``). Este script es el único
camino para regenerarlo.

Qué hace
--------
1. Lee la revisión humana vigente por expediente
   (``FeedbackRepository.filas_revision_ti``: una fila por expediente, la más
   reciente, ya unida con lo que hace falta de ``licitaciones``).
2. La convierte en :class:`~services.ml.golden_ti.EjemploGoldenTi`
   (``ejemplo_desde_fila``) y reparte tune/holdout por fecha, fijo
   (``repartir``): contra el corte que ya guarda la cabecera del fichero de
   destino; si ese no lo trae (una ``--salida`` nueva), contra el del golden
   del repo; y solo en la primera exportación, contra la mediana, de modo que
   el holdout es el 50% más reciente. El corte no se recalcula después:
   revisar más tarde una licitación antigua no mueve ningún ejemplo de tune a
   holdout, y copiar una ``--salida`` encima del golden no mueve el corte.
3. Escribe el JSONL con cabecera, la línea del corte y una línea por
   ejemplo, ordenadas por fecha de publicación.

Uso::

    ENV=dev PYTHONPATH="$PWD" python scripts/exportar_golden_ti.py
    ENV=dev PYTHONPATH="$PWD" python scripts/exportar_golden_ti.py --salida /tmp/golden_ti.jsonl

No toca ``ml_feedback`` ni ``licitaciones``: es de solo lectura salvo por el
propio fichero de salida.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from observability.logging import get_logger  # noqa: E402

log = get_logger(__name__)

_CABECERA = """# Golden set real de «¿es TI?» y familias/fabricantes (plan de clasificación
# en tres niveles, F2). Sustituye a los 27 ejemplos de golden_set.jsonl como
# gate del binario `es_ti`: sale de la revisión humana (`ml_feedback`,
# `source='revision_ti'`), lleva fuente, fecha de publicación, quién etiquetó
# y cuándo, y su holdout es el 50% más reciente por fecha, fijo: la primera
# exportación congela el corte en la línea `corte_holdout` y las siguientes
# reparten contra él (`services.ml.golden_ti.repartir`).
#
# Formato JSONL: una línea por ejemplo (ver `services.ml.golden_ti.EjemploGoldenTi`
# para los campos); las líneas vacías y las que empiezan por '#' se ignoran.
#
# Se genera con:
#   ENV=dev PYTHONPATH="$PWD" python scripts/exportar_golden_ti.py
# tras cada ronda de revisión humana (`ml_feedback.source = 'revision_ti'`).
# NO SE EDITA A MANO.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--salida",
        type=Path,
        default=None,
        help="Ruta de salida (default: tests/fixtures/golden_ti.jsonl)",
    )
    args = parser.parse_args(argv)
    salida: Path | None = args.salida

    from db.database import init_db
    from db.repositories.feedback import FeedbackRepository
    from services.ml.golden_ti import (
        PREFIJO_CORTE_HOLDOUT,
        RUTA_GOLDEN_TI,
        a_linea,
        ejemplo_desde_fila,
        repartir,
    )

    init_db()

    destino = salida if salida is not None else RUTA_GOLDEN_TI
    filas = FeedbackRepository().filas_revision_ti()
    # El corte se lee antes de abrir el destino para escribir: primero el del
    # propio destino y, si no trae ninguno, el del golden del repo, para que
    # una `--salida` nueva no fije una mediana propia. `repartir` ya devuelve
    # la lista ordenada por (fecha, id_externo): el orden en que se escribe.
    ejemplos, corte = repartir([ejemplo_desde_fila(f) for f in filas], destino, RUTA_GOLDEN_TI)

    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(_CABECERA)
        if corte is not None:
            fh.write(f"{PREFIJO_CORTE_HOLDOUT}{corte}\n")
        for ejemplo in ejemplos:
            fh.write(a_linea(ejemplo) + "\n")

    n = len(ejemplos)
    positivos = sum(1 for e in ejemplos if e.es_ti)
    n_tune = sum(1 for e in ejemplos if e.split == "tune")
    n_holdout = n - n_tune
    print(f"Golden TI exportado a {destino}")
    print(
        f"  n={n} · positivos={positivos} · tune={n_tune} · holdout={n_holdout} · "
        f"corte={corte or 'sin fijar'}"
    )
    log.info(
        "exportar_golden_ti.done",
        path=str(destino),
        n=n,
        positivos=positivos,
        n_tune=n_tune,
        n_holdout=n_holdout,
        corte_holdout=corte,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
