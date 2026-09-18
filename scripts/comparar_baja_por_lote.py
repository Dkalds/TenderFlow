"""¿Sustituir el modelo de baja agregado por uno por lote? Mide antes de decidir.

Es la comparación que exige el backlog P2 «Modelo de baja por lote»: si el
``mae_p50`` por lote no mejora al agregado, se documenta y se queda el
agregado. Imprime un JSON con dos bloques, que miden cosas distintas:

- ``backtest``: los dos modelos entrenados con el mismo corte temporal y
  evaluados sobre **los mismos lotes** adjudicados después
  (``services.ml.comparacion_lote``). Responde con el histórico de hoy.
- ``servido``: las predicciones que ``predicciones_baja`` guardó, contra las
  bajas observadas después (``services.ml.calibration.comparar_mae_p50``).
  Solo es informativo cuando ``lote.n_prediccion_por_lote`` > 0, es decir,
  cuando el batch por lote (``ML_BAJA_POR_LOTE``) lleva tiempo corriendo.

No escribe nada, no activa ninguna versión y no cambia la granularidad
servida: la decisión es humana. Requiere una BD con histórico de
adjudicaciones (``DATABASE_URL``).

Uso::

    ENV=dev python scripts/comparar_baja_por_lote.py [--hasta YYYY-MM-DD] [--valid-meses 6]

Exit 0 si se pudo medir (sea cual sea la recomendación); 1 si no hubo datos.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hasta", help="Corte del histórico YYYY-MM-DD (default: todo)")
    parser.add_argument(
        "--valid-meses",
        type=int,
        default=6,
        help="Meses de publicación finales que se evalúan (default: 6)",
    )
    args = parser.parse_args()

    from db.database import init_db
    from services.ml.calibration import comparar_mae_p50
    from services.ml.comparacion_lote import backtest_mae_p50_por_lote

    init_db()
    backtest = backtest_mae_p50_por_lote(hasta=args.hasta, valid_meses=args.valid_meses)
    servido = comparar_mae_p50()
    print(
        json.dumps(
            {"backtest": backtest, "servido": servido},
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0 if backtest.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
