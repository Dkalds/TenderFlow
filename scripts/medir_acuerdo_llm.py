"""Informe: ¿pueden entrenar las etiquetas del LLM? (spec §3.5, Tarea 6).

Por qué existe
---------------
El plan de clasificación en tres niveles etiqueta con un LLM el universo
entero de licitaciones (nivel 1 ``es_ti`` + familias del nivel 2), mucho más
volumen que lo que un humano puede revisar. La spec (§3.5) exige medir el
acuerdo de esas etiquetas con el golden humano antes de usarlas para
entrenar: ``services.ml.acuerdo_llm.medir_acuerdo`` aplica esa regla y este
script junta las tres piezas (golden, respuesta vigente del LLM, y la
función pura) en un informe legible.

Es un informe, no un gate: **siempre sale con 0**, incluso con veredicto
NO APTO -- decidir qué hacer con ese veredicto es de quien lo lee (persona o,
más adelante, un paso de pipeline que si quiere bloquear algo lo hace con su
propio código de salida).

Qué hace
--------
1. Carga el golden set real (``services.ml.golden_ti.cargar_golden_ti``).
2. Pide la respuesta vigente del LLM para esos expedientes
   (``TecnologiaPliegoRepository.respuestas_llm_vigentes``) y la convierte a
   :class:`~services.ml.acuerdo_llm.RespuestaLlm`.
3. Mide el acuerdo (``medir_acuerdo``) e imprime ``n_comparables``, el
   acuerdo en ``es_ti``, la F1 por familia, las familias sin soporte
   suficiente y el veredicto ``APTO``/``NO APTO`` con sus motivos.

Uso::

    ENV=dev PYTHONPATH="$PWD" python scripts/medir_acuerdo_llm.py
    ENV=dev PYTHONPATH="$PWD" python scripts/medir_acuerdo_llm.py --golden /tmp/otro_golden.jsonl

No escribe nada: ni en la BD ni en el golden set.
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--golden",
        type=Path,
        default=None,
        help="Ruta al golden set JSONL (default: tests/fixtures/golden_ti.jsonl)",
    )
    args = parser.parse_args(argv)
    golden_path: Path | None = args.golden

    from db.database import init_db
    from db.repositories.tecnologia_pliego import TecnologiaPliegoRepository
    from services.ml.acuerdo_llm import (
        ACUERDO_MIN_ES_TI,
        SOPORTE_MIN_FAMILIA,
        RespuestaLlm,
        medir_acuerdo,
    )
    from services.ml.golden_ti import cargar_golden_ti

    init_db()

    golden = cargar_golden_ti(golden_path)
    ids = [ejemplo.id_externo for ejemplo in golden]
    vigentes = TecnologiaPliegoRepository().respuestas_llm_vigentes(ids)
    respuestas = {
        id_externo: RespuestaLlm(es_ti=datos["es_ti"], familias=frozenset(datos["familias"]))
        for id_externo, datos in vigentes.items()
    }

    acuerdo = medir_acuerdo(golden, respuestas)

    print(f"Golden: n={len(golden)} · comparables={acuerdo.n_comparables}")
    if acuerdo.acuerdo_es_ti is None:
        print("es_ti: sin comparables")
    else:
        print(f"es_ti: acuerdo={acuerdo.acuerdo_es_ti:.2f} (mínimo {ACUERDO_MIN_ES_TI:.2f})")

    if acuerdo.f1_por_familia:
        print("F1 por familia:")
        for familia in sorted(acuerdo.f1_por_familia):
            print(f"  {familia}: {acuerdo.f1_por_familia[familia]:.2f}")
    else:
        print("F1 por familia: ninguna con soporte suficiente")

    if acuerdo.sin_soporte:
        print(
            f"Sin soporte suficiente (< {SOPORTE_MIN_FAMILIA} aciertos + errores "
            f"sobre los TI humanos): {', '.join(acuerdo.sin_soporte)}"
        )

    veredicto = "APTO" if acuerdo.apto else "NO APTO"
    print(f"Veredicto: {veredicto}")
    for motivo in acuerdo.motivos:
        print(f"  - {motivo}")

    log.info(
        "medir_acuerdo_llm.done",
        n_golden=len(golden),
        n_comparables=acuerdo.n_comparables,
        acuerdo_es_ti=acuerdo.acuerdo_es_ti,
        apto=acuerdo.apto,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
