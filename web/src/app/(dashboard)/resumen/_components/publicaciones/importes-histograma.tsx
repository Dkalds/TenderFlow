"use client";

/**
 * Importes — histograma logarítmico de `histogram_bins`.
 *
 * Responde «de qué tamaño es lo que se publica», que es la pregunta que el eje
 * Y de la nube intentaba contestar y no podía: el 71 % de los importes está por
 * debajo de 1.000 € y el eje llegaba a 16 M. Los tramos los calcula el backend
 * sobre el periodo completo; aquí sólo se reparte el ancho de cada barra sobre
 * el máximo, y el porcentaje va contra el total de expedientes **con importe
 * declarado**, que es el denominador que el pie declara.
 */

import { PanelEmpty } from "@/components/console/panel";
import { getSeriesColor } from "@/lib/chart-colors";
import { formatNumber } from "@/lib/utils";
import type { HistogramBin } from "@/lib/api-types";
import { ALTO } from "./publicaciones-data";

export interface ImportesHistogramaProps {
  histograma: HistogramBin[];
  /** Expedientes con importe declarado: el denominador de los porcentajes. */
  total: number;
  /** Mayor recuento de la serie: fija el 100 % del ancho de barra. */
  maximo: number;
}

export function ImportesHistograma({ histograma, total, maximo }: ImportesHistogramaProps) {
  if (histograma.length === 0) {
    return (
      <PanelEmpty message="Ningún expediente del periodo declara importe." height={ALTO} />
    );
  }

  return (
    <>
      <div className="min-h-[288px]">
        {histograma.map((bin, indice) => {
          const pct = total ? (bin.count / total) * 100 : 0;
          return (
            <div key={bin.bin_label} className="px-1 py-1.5">
              <span className="flex items-baseline gap-2">
                <span className="tf-tnum w-[76px] flex-none font-mono text-[11px]">
                  {bin.bin_label}
                </span>
                <span className="flex-1" />
                <span className="text-muted-foreground/80 tf-tnum flex-none font-mono text-[10px]">
                  {pct.toFixed(1).replace(".", ",")}%
                </span>
                <span className="tf-tnum flex-none font-mono text-[11px] font-semibold">
                  {formatNumber(bin.count)}
                </span>
              </span>
              <span className="bg-border/40 mt-1 block h-1.5 overflow-hidden rounded-full">
                <span
                  className="block h-full rounded-full transition-[width] duration-200 ease-out"
                  style={{
                    width: `${maximo ? Math.max(1, (bin.count / maximo) * 100) : 0}%`,
                    background: getSeriesColor(indice),
                  }}
                />
              </span>
            </div>
          );
        })}
      </div>
      <p className="text-muted-foreground mt-2 text-[10.5px] leading-[1.45]">
        {formatNumber(total)} expedientes con importe declarado. Los tramos son logarítmicos y
        los calcula el backend sobre el periodo completo.
      </p>
    </>
  );
}
