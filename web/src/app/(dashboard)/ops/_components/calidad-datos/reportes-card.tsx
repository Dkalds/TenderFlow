"use client";

/**
 * F6.2 — reportes de dato abiertos, por tipo.
 *
 * Es la otra mitad de la pantalla de Calidad: los demás paneles dicen lo que
 * la máquina sabe que falta; éste, lo que una persona ha visto mal desde la
 * ficha. Los conteos son los de `/analytics/quality` (`reportes_por_tipo`);
 * aquí sólo se etiquetan y se ordenan. Un tipo que el backend no manda no se
 * pinta a cero: no se ha medido.
 */

import { Panel, PanelEmpty, PanelTitle } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { CABECERA_COLUMNA } from "@/components/ui/table";
import { TIPOS_REPORTE, type TipoReporte } from "@/hooks/use-reportar-dato";
import { cn, formatNumber } from "@/lib/utils";

export interface ReportesCardProps {
  reportes: Record<string, number> | undefined;
  isLoading: boolean;
}

export function ReportesCard({ reportes, isLoading }: ReportesCardProps) {
  const filas = Object.entries(reportes ?? {})
    .filter(([, n]) => n > 0)
    .sort(([, a], [, b]) => b - a);

  return (
    <Panel>
      <PanelTitle title="Datos reportados por los usuarios" />
      {isLoading ? (
        <Skeleton className="h-16 w-full" />
      ) : filas.length === 0 ? (
        <PanelEmpty
          size="sm"
          title="Ningún reporte abierto."
          hint="Lo que alguien marque como erróneo desde la ficha de una licitación aparecerá aquí, por tipo."
        />
      ) : (
        <table className="w-full max-w-md text-tf-body">
          <caption className="sr-only">Reportes abiertos por tipo</caption>
          <thead>
            <tr className="border-b border-border/60 text-left">
              <th scope="col" className={cn("py-1.5", CABECERA_COLUMNA)}>
                Tipo
              </th>
              <th scope="col" className={cn("py-1.5 text-right", CABECERA_COLUMNA)}>
                Abiertos
              </th>
            </tr>
          </thead>
          <tbody>
            {filas.map(([tipo, n]) => (
              <tr key={tipo} className="border-b border-border/40 last:border-b-0">
                <td className="py-1.5">{TIPOS_REPORTE[tipo as TipoReporte] ?? tipo}</td>
                <td className="tf-tnum py-1.5 text-right font-medium">{formatNumber(n)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}
