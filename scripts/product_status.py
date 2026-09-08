"""Imprime métricas de producto reproducibles desde la base configurada."""

from __future__ import annotations

import argparse
import json

from db.database import init_db
from services.product_metrics import get_product_status
from shared.dto import RadarQuality


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
    print("Unidad de conteo:           oportunidad (una por lote, no por expediente)")
    print(f"Oportunidades identificadas: {totals.pursuits_identified}")
    print(f"Ofertas presentadas:        {totals.pursuits_submitted}")
    print(f"Ganadas / perdidas:         {totals.pursuits_won} / {totals.pursuits_lost}")
    print(f"Win rate resuelto:          {win_rate}")
    print(f"Importe adjudicado:         {totals.awarded_amount_eur:,.2f} EUR")
    print(f"Mediana hasta decisión:     {decision_time}")
    _print_radar_quality(totals.radar_quality)
    _imprimir_gonogo()


def _print_radar_quality(calidad: RadarQuality | None) -> None:
    """Imprime la precisión del Radar por banda, o por qué no se puede.

    Ninguna línea sale sin su denominador (ADR-014): por debajo del mínimo se
    dice «sin datos suficientes» y se enseña la base, en vez de un porcentaje
    que una sola oportunidad movería veinte puntos.
    """
    print()
    print("Calidad del Radar (precisión por banda de entrada)")
    if calidad is None:
        print(
            "  Sin datos: ninguna oportunidad lleva banda sellada. Se sella al "
            "abrirla desde el Radar (revisión v93)."
        )
        return
    desde = calidad.ventana_desde.date().isoformat() if calidad.ventana_desde else "inicio"
    hasta = calidad.ventana_hasta.date().isoformat() if calidad.ventana_hasta else "hoy"
    origen = "periodo pedido" if calidad.ventana_origen == "periodo_solicitado" else "histórico"
    print(f"  Ventana ({origen}): {desde} → {hasta}")
    print(
        f"  Cobertura: {calidad.pursuits_con_banda}/{calidad.pursuits_total} "
        "oportunidades con banda sellada"
    )
    for banda in calidad.bandas:
        if banda.precision is None:
            detalle = (
                f"sin datos suficientes ({banda.resueltas}/{calidad.minimo_por_banda} resueltas)"
            )
        else:
            detalle = f"{banda.precision:.1%} ({banda.ganadas}/{banda.resueltas} resueltas)"
        cierre = (
            "n/d"
            if banda.tasa_cierre is None
            else f"{banda.tasa_cierre:.1%} ({banda.cerradas}/{banda.abiertas})"
        )
        print(f"  {banda.banda:<10} precisión: {detalle} · cierre: {cierre}")


def _imprimir_gonogo() -> None:
    """«Go por debajo del umbral» (C6.4, D30).

    No es una alerta ni un bloqueo: la decisión de presentarse la toman las
    personas. Es una cifra que, mirada mes a mes, distingue dos cosas que desde
    dentro se sienten igual — una plantilla mal calibrada (todo puntúa bajo y aun
    así se gana) de una falta de disciplina (se dice `go` a lo que el propio
    equipo puntuó mal, y se pierde).

    Best-effort: `product-status` es un informe, y una métrica que no se puede
    calcular no puede llevarse por delante las otras seis.
    """
    from db.repositories.pursuits import PursuitRepository
    from services.gonogo import UMBRAL_POR_DEFECTO

    try:
        datos = PursuitRepository().go_bajo_umbral(umbral=UMBRAL_POR_DEFECTO)
    except Exception as exc:
        print(f"Go/no-go:                   no medido ({str(exc)[:60]})")
        return
    if not datos["puntuados"]:
        # Cero puntuados no es «cero problemas»: es que nadie usa la plantilla.
        print("Go/no-go:                   sin puntuar (0 expedientes)")
        return
    media = "n/d" if datos["media"] is None else f"{datos['media']:.1f}"
    print(
        f"Go bajo umbral ({datos['umbral']:.0f}):     "
        f"{datos['go_bajo_umbral']} de {datos['go']} go · "
        f"{datos['puntuados']} puntuados · media {media}"
    )


if __name__ == "__main__":
    main()
