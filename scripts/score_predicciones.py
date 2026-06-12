"""Batch de scoring/entrenamiento de modelos predictivos (RFC 20260611-2).

Uso:
    python scripts/score_predicciones.py            # scoring batch (nocturno)
    python scripts/score_predicciones.py --train    # re-entrena y registra versión
    python scripts/score_predicciones.py --train --activate   # además la activa
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", action="store_true", help="Re-entrena el modelo de baja")
    parser.add_argument(
        "--activate", action="store_true",
        help="Con --train: activa la versión aunque ML_PRED_AUTO_ACTIVATE esté off",
    )
    parser.add_argument("--hasta", help="Fecha de corte de entrenamiento YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=5000, help="Máx. licitaciones a puntuar")
    args = parser.parse_args()

    from db.database import init_db

    init_db()

    if args.train:
        from services.ml.baja_model import entrenar

        resumen = entrenar(hasta=args.hasta, activar=True if args.activate else None)
        print(f"Entrenamiento: {resumen}")
        if resumen.get("status") != "ok":
            return 1

    from services.ml.scoring import score_predicciones_baja

    stats = score_predicciones_baja(limit=args.limit)
    print(
        f"Scoring baja: {stats['filas']} filas · serving={stats.get('serving', '-')} "
        f"· model_version={stats.get('model_version')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
