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
import { formatNumber, formatPercent } from "@/lib/utils";
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
      <PanelEmpty
        title="Ningún expediente del periodo declara importe"
        hint="Amplía las fechas del ámbito para ver cómo se reparten los importes."
        height={ALTO}
      />
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
                <span className="tf-tnum w-[76px] flex-none text-tf-micro">{bin.bin_label}</span>
                <span className="flex-1" />
                <span className="tf-tnum flex-none text-tf-micro text-muted-foreground">
                  {formatPercent(pct)}
                </span>
                <span className="tf-tnum flex-none text-tf-micro font-semibold">
                  {formatNumber(bin.count)}
                </span>
              </span>
              <span className="mt-1 block h-1.5 overflow-hidden rounded-full bg-border/40">
                <span
                  className="block h-full rounded-full"
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
      <p className="mt-2 text-tf-micro text-muted-foreground">
        {formatNumber(total)} expedientes con importe declarado en todo el periodo, en tramos de
        escala logarítmica.
      </p>
    </>
  );
}
