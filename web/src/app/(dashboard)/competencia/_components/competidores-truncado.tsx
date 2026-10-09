"use client";

/**
 * Aviso de ámbito recortado, junto a las cifras que afecta.
 *
 * `/analytics/competitors` analiza como mucho las `limite_filas` adjudicaciones
 * más recientes del ámbito. Cuando el ámbito tiene más, la respuesta lo dice
 * con `truncado`, y las cuotas, el índice de concentración y los totales de la
 * pantalla dejan de ser los del ámbito entero. La API lo avisaba y la pantalla
 * no lo enseñaba.
 *
 * Sin recorte no pinta nada: es una advertencia, no un indicador de estado.
 */

import { Aviso } from "@/components/console/panel";
import { formatNumber } from "@/lib/utils";

export function CompetidoresTruncado({ truncado, limite }: { truncado: boolean | undefined; limite: number | undefined }) {
  if (!truncado) return null;
  const tope = limite != null ? formatNumber(limite, "es-ES", { agruparSiempre: true }) : null;
  return (
    <Aviso tone="warning" role="note" title="Ámbito recortado">
      El ámbito tiene más adjudicaciones de las que se analizan de una vez
      {tope ? `: las cuotas, la concentración y los totales salen de las ${tope} más recientes` : ""}. Acota las
      fechas o añade un filtro para verlo entero.
    </Aviso>
  );
}
