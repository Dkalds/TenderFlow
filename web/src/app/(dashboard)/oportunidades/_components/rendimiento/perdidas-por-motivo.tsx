"use client";

/**
 * F3.1 — por qué se pierde. La API sólo publica el reparto con un mínimo
 * de pérdidas (`perdidas_n_minimo`); por debajo se dice cuántas faltan en vez
 * de enseñar porcentajes sobre dos casos.
 */
import { Panel, PanelTitle } from "@/components/console/panel";
import type { PursuitMetrics } from "@/hooks/use-pursuits";
import { etiquetaMotivo, repartoPerdidas } from "@/lib/motivos-perdida";
import { CABECERA_COLUMNA } from "@/components/ui/table";
import { cn, formatNumber } from "@/lib/utils";

export function PerdidasPorMotivo({ metrics }: { metrics: PursuitMetrics }) {
  const reparto = repartoPerdidas(metrics);
  return (
    <Panel>
      {/* «En la ventana» y no «histórico»: desde que la vista tiene selector de
          periodo, el backend cuenta las pérdidas del periodo pedido. */}
      <PanelTitle title="Pérdidas por motivo" hint="Cerradas en la ventana" />
      {reparto.estado === "insuficiente" ? (
        <p role="status" className="text-tf-meta leading-normal text-muted-foreground">
          El reparto se publica a partir de {reparto.minimo} pérdidas cerradas; hay{" "}
          {formatNumber(reparto.perdidas)}. Por debajo, el porcentaje diría más de la casualidad
          que del equipo.
        </p>
      ) : (
        <table className="w-full text-tf-meta">
          <caption className="sr-only">Pérdidas por motivo</caption>
          <thead>
            <tr className="text-left">
              <th scope="col" className={cn(CABECERA_COLUMNA, "pb-1.5")}>
                Motivo
              </th>
              <th scope="col" className={cn(CABECERA_COLUMNA, "pb-1.5 text-right")}>
                Pérdidas
              </th>
              <th scope="col" className={cn(CABECERA_COLUMNA, "pb-1.5 text-right")}>
                %
              </th>
            </tr>
          </thead>
          <tbody>
            {reparto.filas.map((fila) => (
              <tr key={fila.motivo} className="border-t border-border/50">
                <td className="py-1.5">{etiquetaMotivo(fila.motivo)}</td>
                <td className="tf-tnum py-1.5 text-right">{formatNumber(fila.n)}</td>
                <td className="tf-tnum py-1.5 text-right">
                  {Math.round(fila.pct * 100)} %
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}
