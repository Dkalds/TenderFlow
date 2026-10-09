"use client";

/**
 * Los dos rankings en uno: el nombre en el centro, las licitaciones crecen hacia
 * la izquierda y el importe hacia la derecha, cada ala a escala de su máximo.
 * La asimetría de las alas es el dato: un órgano con el ala derecha más larga
 * compra pocos contratos pero grandes.
 *
 * Es una tabla, y el destino del clic es un botón real en la celda del nombre:
 * el teclado y el lector de pantalla recorren aquí lo que el mapa sólo ofrece
 * al ratón. El `onClick` del `<tr>` se queda como atajo sobre el resto de la fila.
 */

import { Panel, PanelTitle, Segmented } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Pista } from "@/components/ui/pista";
import { CHART_SERIES } from "@/lib/chart-colors";
import { cn, formatCurrency, formatNumber } from "@/lib/utils";

import { FILAS_MARIPOSA, type FilaMariposa, type MetricaOrganos } from "../_hooks/use-organos-view";
import { OPCIONES_METRICA } from "./organos-cabecera";

/** Un ala de la mariposa: un SVG sin estilo en línea, con el ancho en el propio `rect`. */
function Ala({ pct, lado, color }: { pct: number; lado: "izquierda" | "derecha"; color: string }) {
  const ancho = Math.max(0, Math.min(100, pct));
  return (
    <svg
      aria-hidden="true"
      className="h-3.5 w-full"
      viewBox="0 0 100 10"
      preserveAspectRatio="none"
    >
      <rect x={lado === "izquierda" ? 100 - ancho : 0} y="0" width={ancho} height="10" fill={color} />
    </svg>
  );
}

export function OrganosMariposa({
  filas,
  metrica,
  onMetricaChange,
  totalOrganos,
  filtrado,
  isLoading,
  onOrganoClick,
}: {
  filas: FilaMariposa[];
  metrica: MetricaOrganos;
  onMetricaChange: (metrica: MetricaOrganos) => void;
  totalOrganos: number | null;
  filtrado: boolean;
  isLoading: boolean;
  onOrganoClick: (organo: string) => void;
}) {
  const ordenTxt = metrica === "count" ? "licitaciones" : "importe";
  return (
    <Panel>
      <PanelTitle
        title={`Los ${FILAS_MARIPOSA} primeros, por las dos medidas`}
        hint={`ordenado por ${ordenTxt} · pulsa un órgano para abrir su perfil`}
        actions={
          <>
            {filtrado && (
              <Badge variant="neutral" size="sm">
                Filtrado
              </Badge>
            )}
            <Segmented
              value={metrica}
              onChange={onMetricaChange}
              options={OPCIONES_METRICA}
              aria-label="Ordenar por"
              size="xs"
            />
          </>
        }
      />
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
              <TableHead className="w-[30%] text-right">
                <span className="inline-flex items-center gap-1.5">
                  <svg aria-hidden="true" className="h-2 w-2" viewBox="0 0 8 8">
                    <rect width="8" height="8" rx="2" fill={CHART_SERIES[0]} />
                  </svg>
                  Licitaciones
                </span>
              </TableHead>
              <TableHead className="w-[40%] text-center">Órgano</TableHead>
              <TableHead className="w-[30%]">
                <span className="inline-flex items-center gap-1.5">
                  <svg aria-hidden="true" className="h-2 w-2" viewBox="0 0 8 8">
                    <rect width="8" height="8" rx="2" fill={CHART_SERIES[1]} />
                  </svg>
                  Importe
                </span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filas.map((fila, idx) => (
              <TableRow
                key={fila.organo}
                className={cn("cursor-pointer", fila.seleccionado && "bg-primary/10")}
                onClick={() => onOrganoClick(fila.organo)}
              >
                <TableCell>
                  <div className="flex items-center gap-2">
                    <span className="tf-tnum w-12 shrink-0 text-right text-tf-meta font-semibold">
                      {formatNumber(fila.count)}
                    </span>
                    <Ala pct={fila.pctCount} lado="izquierda" color={CHART_SERIES[0]} />
                  </div>
                </TableCell>
                <TableCell className="max-w-xs">
                  <div className="flex items-center justify-center gap-2">
                    <span
                      className={cn(
                        "tf-tnum w-5 shrink-0 text-right text-tf-meta font-semibold",
                        fila.seleccionado ? "text-primary" : "text-muted-foreground",
                      )}
                    >
                      {idx + 1}
                    </span>
                    <Pista contenido={fila.organo}>
                      <button
                        type="button"
                        className="block min-w-0 max-w-full cursor-pointer truncate text-left transition-colors hover:text-primary"
                        onClick={(e) => {
                          // Sin esto el clic sube al `<tr>` y el handler corre
                          // dos veces por pulsación.
                          e.stopPropagation();
                          onOrganoClick(fila.organo);
                        }}
                      >
                        {fila.organo}
                      </button>
                    </Pista>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <Ala pct={fila.pctImporte} lado="derecha" color={CHART_SERIES[1]} />
                    <span className="tf-tnum w-20 shrink-0 text-tf-meta font-semibold">
                      {formatCurrency(fila.importe)}
                    </span>
                  </div>
                </TableCell>
              </TableRow>
            ))}
            {filas.length === 0 && (
              <TableRow>
                <TableCell colSpan={3} className="py-8 text-center text-muted-foreground">
                  Ningún órgano coincide con la búsqueda en el ámbito actual.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      )}
      {!isLoading && filas.length > 0 && (
        <p className="mt-3 border-t border-border/60 pt-2.5 text-tf-meta text-muted-foreground">
          {totalOrganos != null && totalOrganos > filas.length
            ? `${formatNumber(filas.length)} de ${formatNumber(totalOrganos)} órganos. `
            : ""}
          Un órgano con el ala derecha más larga que la izquierda compra pocos contratos pero grandes.
        </p>
      )}
    </Panel>
  );
}
