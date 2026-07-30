"""Imprime métricas de producto reproducibles desde la base configurada."""

from __future__ import annotations

import argparse
import json

from db.database import init_db
from services.product_metrics import get_product_status


def main() -> None:
    parser = argparse.ArgumentParser(description="Métricas de resultado de TenderFlow")
    parser.add_argument("--from", dest="period_from", help="Inicio ISO inclusivo")
    parser.add_argument("--to", dest="period_to", help="Fin ISO exclusivo")
    parser.add_argument("--json", action="store_true", help="Salida JSON completa")
    args = parser.parse_args()

    init_db()
    status = get_product_status(
        period_from=args.period_from,
        period_to=args.period_to,
    )
    if args.json:
        print(json.dumps(status.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return

    totals = status.totals
    win_rate = "n/d" if totals.win_rate is None else f"{totals.win_rate:.1%}"
    decision_time = (
        "n/d"
        if totals.median_decision_time_hours is None
        else f"{totals.median_decision_time_hours:.1f} h"
    )
    print("TenderFlow · métricas de producto")
    print(f"Oportunidades identificadas: {totals.pursuits_identified}")
    print(f"Ofertas presentadas:        {totals.pursuits_submitted}")
    print(f"Ganadas / perdidas:         {totals.pursuits_won} / {totals.pursuits_lost}")
    print(f"Win rate resuelto:          {win_rate}")
    print(f"Importe adjudicado:         {totals.awarded_amount_eur:,.2f} EUR")
    print(f"Mediana hasta decisión:     {decision_time}")


if __name__ == "__main__":
    main()
