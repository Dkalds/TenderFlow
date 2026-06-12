"""Batch de scoring/entrenamiento de modelos predictivos (RFC 20260611-2).

Uso:
    python scripts/score_predicciones.py                          # scoring batch (ambos modelos)
    python scripts/score_predicciones.py --train                  # re-entrena baja + retención
    python scripts/score_predicciones.py --train --model retencion
    python scripts/score_predicciones.py --train --activate       # además activa la(s) versión(es)

La columna "Riesgo de cambio" de Renovaciones solo se puebla con un modelo
de retención ACTIVO: entrenar (--train --model retencion), auditar los pares
(scripts/audit_retencion.py) y activar (--activate o model_registry).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", action="store_true", help="Re-entrena antes de puntuar")
    parser.add_argument(
        "--model",
        choices=("baja", "retencion", "all"),
        default="all",
        help="Qué modelo entrenar/puntuar (default: all)",
    )
    parser.add_argument(
        "--activate",
        action="store_true",
        help="Con --train: activa la versión aunque ML_PRED_AUTO_ACTIVATE esté off",
    )
    parser.add_argument("--hasta", help="Fecha de corte de entrenamiento YYYY-MM-DD (solo baja)")
    parser.add_argument("--limit", type=int, default=5000, help="Máx. licitaciones a puntuar")
    args = parser.parse_args()

    from db.database import init_db

    init_db()
    fallo = False

    if args.train:
        if args.model in ("baja", "all"):
            from services.ml.baja_model import entrenar as entrenar_baja

            resumen = entrenar_baja(hasta=args.hasta, activar=True if args.activate else None)
            print(f"Entrenamiento baja: {resumen}")
            fallo |= resumen.get("status") != "ok"
        if args.model in ("retencion", "all"):
            from services.ml.retencion_model import entrenar as entrenar_retencion

            resumen = entrenar_retencion(activar=True if args.activate else None)
            print(f"Entrenamiento retención: {resumen}")
            if resumen.get("status") == "ok" and not resumen.get("activado"):
                print(
                    "  ⚠ Versión registrada SIN activar. La columna 'Riesgo de cambio' "
                    "seguirá vacía hasta activarla:\n"
                    "    1) auditá los pares: python scripts/audit_retencion.py\n"
                    "    2) activá: python scripts/score_predicciones.py --train "
                    "--model retencion --activate\n"
                    "       (o db.model_registry.activate_version('retencion_model', N))"
                )
            fallo |= resumen.get("status") != "ok"

    if args.model in ("baja", "all"):
        from services.ml.scoring import score_predicciones_baja

        stats = score_predicciones_baja(limit=args.limit)
        print(
            f"Scoring baja: {stats['filas']} filas · serving={stats.get('serving', '-')} "
            f"· model_version={stats.get('model_version')}"
        )
    if args.model in ("retencion", "all"):
        from services.ml.scoring import score_predicciones_retencion

        stats = score_predicciones_retencion()
        if stats["status"] == "sin_modelo":
            print(
                "Scoring retención: OMITIDO — no hay modelo activo "
                "(entrenar con --train --model retencion y activar tras la auditoría)."
            )
        else:
            print(
                f"Scoring retención: {stats['filas']} filas "
                f"· model_version={stats.get('model_version')} · status={stats['status']}"
            )
    return 1 if fallo else 0


if __name__ == "__main__":
    sys.exit(main())
