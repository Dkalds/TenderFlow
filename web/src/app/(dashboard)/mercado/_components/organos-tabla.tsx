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

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

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
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Listado Completo</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table className="w-full text-sm">
              <TableHeader>
                <TableRow className="border-b text-left">
                  <TableHead className="pb-2 pr-4 font-medium text-muted-foreground">
                    Órgano
                  </TableHead>
                  <TableHead className="pb-2 pr-4 font-medium text-muted-foreground w-40">
                    Licitaciones
                  </TableHead>
                  <TableHead className="pb-2 pr-4 font-medium text-muted-foreground text-right">
                    Importe
                  </TableHead>
                  <TableHead className="pb-2 pr-4 font-medium text-muted-foreground text-right">
                    %
                  </TableHead>
                  <TableHead className="pb-2 font-medium text-muted-foreground">
                    CCAA
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filas.map((item, idx) => (
                  <TableRow
                    key={idx}
                    className="border-b border-border/50 hover:bg-muted/50 cursor-pointer"
                    onClick={() => onOrganoClick(item.organo_contratacion)}
                  >
                    <TableCell className="py-2 pr-4 max-w-xs">
                      {/* `Tooltip` y no `title`: el nombre se trunca por CSS y
                          el atributo nativo no se abre con teclado ni sigue el
                          tema (C7.4). El texto completo sigue siendo el
                          contenido del botón, así que un lector de pantalla lo
                          lee entero de todas formas. */}
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <button
                            type="button"
                            className="block w-full max-w-full cursor-pointer truncate text-left"
                            onClick={(e) => {
                              // Sin esto el clic sube al `<tr>` y el handler
                              // corre dos veces por pulsación.
                              e.stopPropagation();
                              onOrganoClick(item.organo_contratacion);
                            }}
                          >
                            {item.organo_contratacion}
                          </button>
                        </TooltipTrigger>
                        <TooltipContent>{item.organo_contratacion}</TooltipContent>
                      </Tooltip>
                    </TableCell>
                    <TableCell className="py-2 pr-4 w-40">
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 flex-1 rounded-full bg-muted overflow-hidden">
                          <div
                            className="h-full bg-primary rounded-full transition-[width]"
                            style={{ width: `${(item.count / maxCount) * 100}%` }}
                          />
                        </div>
                        <span className="tabular-nums text-xs w-8 text-right shrink-0">
                          {formatNumber(item.count)}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="py-2 pr-4 text-right tabular-nums">
                      {formatCurrency(item.importe)}
                    </TableCell>
                    <TableCell className="py-2 pr-4 text-right tabular-nums">
                      {formatPercent(item.pct)}
                    </TableCell>
                    <TableCell className="py-2">
                      {item.ccaa ? <Badge variant="secondary">{item.ccaa}</Badge> : "-"}
                    </TableCell>
                  </TableRow>
                ))}
                {filas.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                      Sin resultados
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
