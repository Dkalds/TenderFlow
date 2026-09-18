"use client";

/**
 * F6.2 — reportes de dato abiertos, por tipo.
 *
 * Es la otra mitad de la pantalla de Calidad: las demás tarjetas dicen lo que
 * la máquina sabe que falta; ésta, lo que una persona ha visto mal desde la
 * ficha. Los conteos son los de `/analytics/quality` (`reportes_por_tipo`);
 * aquí sólo se etiquetan y se ordenan. Un tipo que el backend no manda no se
 * pinta a cero: no se ha medido.
 */

import { Flag } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { TIPOS_REPORTE, type TipoReporte } from "@/hooks/use-reportar-dato";
import { formatNumber } from "@/lib/utils";

export interface ReportesCardProps {
  reportes: Record<string, number> | undefined;
  isLoading: boolean;
}

export function ReportesCard({ reportes, isLoading }: ReportesCardProps) {
  const filas = Object.entries(reportes ?? {})
    .filter(([, n]) => n > 0)
    .sort(([, a], [, b]) => b - a);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Flag className="h-4 w-4" aria-hidden="true" />
          Datos reportados por los usuarios
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : filas.length === 0 ? (
          <p className="text-sm text-muted-foreground">Ningún reporte abierto.</p>
        ) : (
          <table className="w-full max-w-md text-sm">
            <caption className="sr-only">Reportes abiertos por tipo</caption>
            <thead>
              <tr className="border-b border-border/60 text-left text-xs text-muted-foreground">
                <th scope="col" className="py-1.5 font-medium">Tipo</th>
                <th scope="col" className="py-1.5 text-right font-medium">Abiertos</th>
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
      </CardContent>
    </Card>
  );
}
