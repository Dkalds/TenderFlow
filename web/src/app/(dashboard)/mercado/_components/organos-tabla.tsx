"use client";

/**
 * Listado completo de órganos, con la barra de proporción por cantidad.
 *
 * El destino del clic tiene que EXISTIR para el teclado y para el lector de
 * pantalla. Hacer la fila focusable (`tabIndex` + `onKeyDown`) le daba el foco
 * pero no un rol interactivo: el lector anunciaba una fila de tabla, no algo
 * que se pueda activar. Y ponerle `role="button"` al `<tr>` es peor — deja de
 * ser una fila, así que se pierden encabezados y navegación por columnas. Lo
 * correcto es un control real dentro de la primera celda, rotulado con el
 * nombre de la fila; el `onClick` del `<tr>` se queda como atajo de ratón
 * sobre el resto.
 */

import { Panel, PanelTitle } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { EMPTY, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

import type { OrganoItem } from "../_hooks/use-organos-view";

export function OrganosTabla({
  filas,
  maxCount,
  isLoading,
  onOrganoClick,
}: {
  filas: OrganoItem[];
  /** Cantidad del órgano más activo del listado: es el 100 % de la barra. */
  maxCount: number;
  isLoading: boolean;
  onOrganoClick: (organo: string) => void;
}) {
  return (
    <Panel>
      <PanelTitle title="Todos los órganos" />
      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Órgano</TableHead>
              <TableHead className="w-40">Licitaciones</TableHead>
              <TableHead className="text-right">Importe</TableHead>
              <TableHead className="text-right">%</TableHead>
              <TableHead>CCAA</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filas.map((item, idx) => (
              <TableRow
                key={idx}
                className="cursor-pointer"
                onClick={() => onOrganoClick(item.organo_contratacion)}
              >
                <TableCell className="max-w-xs">
                  {/* El botón ya era una parada de tabulación: el
                      `Tooltip` no añade ninguna y, a diferencia del
                      `title`, también se abre con el foco. */}
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        className="block w-full max-w-full cursor-pointer truncate text-left transition-colors hover:text-primary"
                        onClick={(e) => {
                          // Sin esto el clic sube al `<tr>` y el handler corre
                          // dos veces por pulsación.
                          e.stopPropagation();
                          onOrganoClick(item.organo_contratacion);
                        }}
                      >
                        {item.organo_contratacion}
                      </button>
                    </TooltipTrigger>
                    <TooltipContent className="max-w-[22rem] text-pretty">{item.organo_contratacion}</TooltipContent>
                  </Tooltip>
                </TableCell>
                <TableCell className="w-40">
                  <div className="flex items-center gap-2">
                    {/* Proporción sin transición: es una medida, no algo
                        que se mueva al cambiar de ámbito. */}
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full bg-primary"
                        style={{ width: `${(item.count / maxCount) * 100}%` }}
                      />
                    </div>
                    <span className="w-8 shrink-0 text-right text-tf-meta">{formatNumber(item.count)}</span>
                  </div>
                </TableCell>
                <TableCell numeric>{formatCurrency(item.importe)}</TableCell>
                <TableCell numeric>{formatPercent(item.pct)}</TableCell>
                <TableCell className="text-muted-foreground">{item.ccaa ?? EMPTY}</TableCell>
              </TableRow>
            ))}
            {filas.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                  Ningún órgano coincide con la búsqueda en el ámbito actual.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      )}
    </Panel>
  );
}
