"""EDA reproducible del target de baja (paso 2 del RFC 20260611-2).

Imprime: distribución real del target (baja agregada por expediente), volumen
de pares válidos por segmento CPV-2, cobertura de la competencia histórica del
segmento y candidatos a truncamiento de outliers. Decide los parámetros del
modelo sin tocar código de producción.

Uso: python scripts/eda_baja.py [--hasta YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hasta", help="Fecha de corte YYYY-MM-DD (default: todo)")
    args = parser.parse_args()

    from db.database import init_db
    from services.ml.features import construir_dataset_baja

    init_db()
    filas, _ = construir_dataset_baja(hasta=args.hasta)
    if not filas:
        print("Sin pares válidos. ¿BD vacía o sin adjudicaciones?")
        return 1

    bajas = sorted(float(f.baja or 0.0) for f in filas)
    n = len(bajas)

    def pct(p: float) -> float:
        return bajas[min(int(n * p), n - 1)]

    print(
        f"== Target: baja agregada = 1 - adjudicado / presupuesto de los lotes "
        f"adjudicados — {n} expedientes válidos =="
    )
    print(f"  media={sum(bajas) / n:.4f}  p5={pct(0.05):.4f}  p25={pct(0.25):.4f}")
    print(f"  p50={pct(0.50):.4f}  p75={pct(0.75):.4f}  p95={pct(0.95):.4f}  p99={pct(0.99):.4f}")
    print(
        f"  max={bajas[-1]:.4f}  · negativos (adjudicado>presupuesto): "
        f"{sum(1 for b in bajas if b < 0)} ({sum(1 for b in bajas if b < 0) * 100 / n:.1f}%)"
    )
    print(
        f"  Sugerencia de truncamiento: clip superior en p99={pct(0.99):.3f} "
        f"(el modelo usa 0.95 fijo; ajustar si p99 difiere mucho)"
    )

    # `n_ofertas` ya no es feature (solo existe después de adjudicar, así que en
    # scoring era NaN siempre). Lo que se mide ahora es la cobertura de la
    # competencia HISTÓRICA del segmento, que sí está disponible al predecir.
    con_ofertas = sum(1 for f in filas if f.features.get("n_ofertas_media_cpv4") is not None)
    print(
        f"\n== Competencia histórica por CPV-4 poblada: {con_ofertas}/{n} "
        f"({con_ofertas * 100 / n:.1f}%) =="
    )

    por_cpv2 = Counter(str(f.features["cpv2"]) for f in filas)
    print("\n== Volumen por CPV-2 (top 15) ==")
    for cpv2, count in por_cpv2.most_common(15):
        print(f"  {cpv2}: {count}")

    con_hist = sum(1 for f in filas if f.features.get("baja_media_organo_cpv4") is not None)
    print(
        f"\n== Cobertura del agregado órgano-CPV4 (feature más específica): "
        f"{con_hist}/{n} ({con_hist * 100 / n:.1f}%) =="
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
