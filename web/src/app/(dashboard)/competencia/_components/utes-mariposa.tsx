"use client";

/**
 * Las UTE con más adjudicaciones, con sus dos medidas en una sola lista: el
 * nombre en el centro, las adjudicaciones crecen hacia la izquierda y el
 * importe hacia la derecha, cada ala a escala de su máximo visible. La
 * asimetría de las alas es el dato: una UTE con el ala derecha más larga gana
 * pocos contratos, pero grandes.
 *
 * Cada fila es una UTE entera —el nombre con el que se adjudicó—, no una de
 * las empresas que la forman: quién se alía con quién está en la red.
 */

import { Search } from "lucide-react";

import { Panel, PanelEmpty, PanelTitle } from "@/components/console/panel";
import { Pista } from "@/components/ui/pista";
import { SearchAutocomplete } from "@/components/ui/search-autocomplete";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { CHART_SERIES } from "@/lib/chart-colors";
import { formatCompactCurrency, formatNumber } from "@/lib/utils";

import type { FilaMariposa } from "../_hooks/utes-series";
import { Ala, Muestra } from "./dibujos";

export function UtesMariposa({
  filas,
  total,
  busqueda,
  onBusquedaChange,
  sugerencias,
  isLoading,
}: {
  filas: FilaMariposa[];
  /** Las UTE recibidas: el universo del que salen las filas visibles. */
  total: number;
  busqueda: string;
  onBusquedaChange: (busqueda: string) => void;
  sugerencias: string[];
  isLoading: boolean;
}) {
  return (
    <Panel>
      <PanelTitle
        className="flex-wrap gap-y-2"
        title="Las UTE con más adjudicaciones"
        hint="ordenadas por adjudicaciones"
        actions={
          <SearchAutocomplete
            className="w-56 max-w-full"
            aria-label="Buscar UTE"
            placeholder="Buscar UTE…"
            value={busqueda}
            onChange={onBusquedaChange}
            suggestions={sugerencias}
            leftIcon={<Search className="h-4 w-4" aria-hidden="true" />}
            inputClassName="pl-9"
          />
        }
      />
      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : filas.length === 0 ? (
        <PanelEmpty
          title={busqueda ? "Ninguna UTE coincide con la búsqueda" : "Ninguna UTE"}
          hint={
            busqueda
              ? "Prueba con otro nombre."
              : "No hay UTE adjudicatarias en el ámbito actual. Amplía las fechas o quita filtros."
          }
        />
      ) : (
        <>
          {/* Columnas de ancho fijo: el nombre se recorta en la suya y las alas
              no se quedan sin sitio en una pantalla estrecha. */}
          <Table className="table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead className="w-[30%] text-right">
                  <span className="inline-flex items-center gap-1.5">
                    <Muestra color={CHART_SERIES[0]} className="h-2 w-2" />
                    Adjudicaciones
                  </span>
                </TableHead>
                <TableHead className="w-[40%] text-center">UTE</TableHead>
                <TableHead className="w-[30%]">
                  <span className="inline-flex items-center gap-1.5">
                    <Muestra color={CHART_SERIES[1]} className="h-2 w-2" />
                    Importe
                  </span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filas.map((fila) => (
                <TableRow key={fila.nombre}>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <span className="tf-tnum w-9 shrink-0 text-right text-tf-meta font-semibold">
                        {formatNumber(fila.count)}
                      </span>
                      <Ala pct={fila.pctCount} lado="izquierda" color={CHART_SERIES[0]} />
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex min-w-0 items-center justify-center gap-2">
                      <span className="tf-tnum w-5 shrink-0 text-right text-tf-meta font-semibold text-muted-foreground">
                        {fila.puesto}
                      </span>
                      <Pista contenido={fila.nombre}>
                        <span className="block min-w-0 truncate">{fila.nombre}</span>
                      </Pista>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <Ala pct={fila.pctImporte} lado="derecha" color={CHART_SERIES[1]} />
                      <span className="tf-tnum w-16 shrink-0 text-tf-meta font-semibold">
                        {formatCompactCurrency(fila.importe)}
                      </span>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="mt-3 border-t border-border/60 pt-2.5 text-tf-meta text-muted-foreground">
            {formatNumber(filas.length)} de {formatNumber(total)} UTE. Una UTE con el ala derecha más larga que la
            izquierda gana pocos contratos, pero grandes.
          </p>
        </>
      )}
    </Panel>
  );
}
