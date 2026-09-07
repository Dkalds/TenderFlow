"use client";

/**
 * Las tres tablas de «Proyectos y módulos»: módulos (ordenable), tipos de
 * proyecto y códigos CPV.
 *
 * Sólo la primera es ordenable, y por eso es la única que recibe `sortKey` /
 * `onSort`: las otras dos llegan ya ordenadas por el llamante.
 */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { formatCurrency, formatNumber } from "@/lib/utils";
import { ArrowUpDown } from "lucide-react";

import type { Schemas } from "@/lib/api-types";
import type { ModSortKey, ModuloConMedia, TipoProyectoRow } from "../_hooks/use-proyectos-modulos-view";

const TH = "pb-2 pr-4 font-medium text-muted-foreground";

function FilasCargando({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

const COLUMNAS_MODULO: [ModSortKey, string][] = [
  ["modulo", "Módulo"],
  ["count", "Cantidad"],
  ["importe", "Importe Total"],
  ["importe_medio", "Importe Medio"],
];

export function ProyectosModulosTabla({
  filas,
  isLoading,
  onSort,
}: {
  filas: ModuloConMedia[];
  isLoading: boolean;
  onSort: (key: ModSortKey) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Importe Medio por Módulo SAP</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <FilasCargando />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left">
                  {COLUMNAS_MODULO.map(([key, label]) => (
                    <th
                      key={key}
                      className={`${TH} ${key !== "modulo" ? "text-right" : ""}`}
                    >
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-auto p-0 font-medium text-muted-foreground hover:text-foreground"
                        onClick={() => onSort(key)}
                      >
                        {label}
                        <ArrowUpDown className="ml-1 h-3 w-3" />
                      </Button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filas.map((item, idx) => (
                  <tr key={idx} className="border-b border-border/50 hover:bg-muted/50">
                    <td className="py-2 pr-4 font-medium">{item.modulo}</td>
                    <td className="py-2 pr-4 text-right tabular-nums">
                      {formatNumber(item.count)}
                    </td>
                    <td className="py-2 pr-4 text-right tabular-nums">
                      {formatCurrency(item.importe)}
                    </td>
                    <td className="py-2 pr-4 text-right tabular-nums">
                      {formatCurrency(item.importe_medio)}
                    </td>
                  </tr>
                ))}
                {filas.length === 0 && (
                  <tr>
                    <td colSpan={4} className="py-8 text-center text-muted-foreground">
                      Sin datos
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function ProyectosTiposTabla({
  tipos,
  isLoading,
}: {
  tipos: TipoProyectoRow[];
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Tipos de Proyecto</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <FilasCargando />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left">
                  <th className={TH}>Tipo</th>
                  <th className={`${TH} text-right`}>Cantidad</th>
                  <th className="pb-2 font-medium text-muted-foreground text-right">Importe</th>
                </tr>
              </thead>
              <tbody>
                {[...tipos]
                  .sort((a, b) => b.count - a.count)
                  .map((item, idx) => (
                    <tr key={idx} className="border-b border-border/50 hover:bg-muted/50">
                      <td className="py-2 pr-4 font-medium">{item.tipo}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">
                        {formatNumber(item.count)}
                      </td>
                      <td className="py-2 text-right tabular-nums">
                        {formatCurrency(item.importe)}
                      </td>
                    </tr>
                  ))}
                {tipos.length === 0 && (
                  <tr>
                    <td colSpan={3} className="py-8 text-center text-muted-foreground">
                      Sin datos
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function ProyectosCpvTabla({
  filas,
  isLoading,
}: {
  filas: Schemas["CpvEntry"][];
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Top códigos CPV</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <FilasCargando />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left">
                  <th className={TH}>CPV</th>
                  <th className={`${TH} text-right`}>Licitaciones</th>
                  <th className="pb-2 text-right font-medium text-muted-foreground">Importe</th>
                </tr>
              </thead>
              <tbody>
                {filas.map((item) => (
                  <tr key={item.cpv} className="border-b border-border/50 hover:bg-muted/50">
                    <td className="py-2 pr-4">
                      <span className="block max-w-md truncate" title={item.cpv_desc}>
                        {item.cpv_desc}
                      </span>
                    </td>
                    <td className="py-2 pr-4 text-right tabular-nums">
                      {formatNumber(item.count)}
                    </td>
                    <td className="py-2 text-right tabular-nums">
                      {formatCurrency(item.importe)}
                    </td>
                  </tr>
                ))}
                {filas.length === 0 && (
                  <tr>
                    <td colSpan={3} className="py-8 text-center text-muted-foreground">
                      Sin datos
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
