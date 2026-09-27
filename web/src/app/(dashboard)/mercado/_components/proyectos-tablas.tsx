"use client";

/**
 * Las tres tablas de «Proyectos y módulos»: módulos (ordenable), tipos de
 * proyecto y códigos CPV.
 *
 * Sólo la primera es ordenable, y por eso es la única que recibe `sortKey` /
 * `onSort`: las otras dos llegan ya ordenadas por el llamante.
 */

import { Panel, PanelTitle } from "@/components/console/panel";
import { IndicadorOrden } from "@/components/ui/data-table";
import { Pista } from "@/components/ui/pista";
import { Skeleton } from "@/components/ui/skeleton";
import {
  CABECERA_COLUMNA,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn, formatCurrency, formatNumber } from "@/lib/utils";

import type { Schemas } from "@/lib/api-types";
import type { ModSortKey, ModuloConMedia, TipoProyectoRow } from "../_hooks/use-proyectos-modulos-view";

function FilasCargando({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-9 w-full" />
      ))}
    </div>
  );
}

/** Fila de «no hay nada» dentro de una tabla. */
function FilaVacia({ columnas, children }: { columnas: number; children: React.ReactNode }) {
  return (
    <TableRow>
      <TableCell colSpan={columnas} className="py-8 text-center text-muted-foreground">
        {children}
      </TableCell>
    </TableRow>
  );
}

const COLUMNAS_MODULO: [ModSortKey, string][] = [
  ["modulo", "Módulo"],
  ["count", "Licitaciones"],
  ["importe", "Importe total"],
  ["importe_medio", "Importe medio"],
];

export function ProyectosModulosTabla({
  filas,
  isLoading,
  sortKey,
  sortDir,
  onSort,
}: {
  filas: ModuloConMedia[];
  isLoading: boolean;
  /** Columna y sentido del orden activo: la cabecera los anuncia (`aria-sort`). */
  sortKey: ModSortKey;
  sortDir: "asc" | "desc";
  onSort: (key: ModSortKey) => void;
}) {
  return (
    <Panel>
      <PanelTitle title="Importe medio por módulo SAP" />
      {isLoading ? (
        <FilasCargando />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              {COLUMNAS_MODULO.map(([key, label]) => {
                const activa = sortKey === key;
                return (
                  <TableHead
                    key={key}
                    aria-sort={activa ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
                    className={cn(key !== "modulo" && "text-right")}
                  >
                    {/* La versal va en el botón: el navegador no se la hereda. */}
                    <button
                      type="button"
                      onClick={() => onSort(key)}
                      className={cn(
                        CABECERA_COLUMNA,
                        "group inline-flex items-center gap-1 transition-colors hover:text-foreground",
                        activa && "text-foreground",
                      )}
                    >
                      {label}
                      <IndicadorOrden direccion={activa ? sortDir : null} />
                    </button>
                  </TableHead>
                );
              })}
            </TableRow>
          </TableHeader>
          <TableBody>
            {filas.map((item, idx) => (
              <TableRow key={idx}>
                <TableCell className="font-medium">{item.modulo}</TableCell>
                <TableCell numeric>{formatNumber(item.count)}</TableCell>
                <TableCell numeric>{formatCurrency(item.importe)}</TableCell>
                <TableCell numeric>{formatCurrency(item.importe_medio)}</TableCell>
              </TableRow>
            ))}
            {filas.length === 0 && (
              <FilaVacia columnas={4}>Ninguna licitación del ámbito actual menciona un módulo SAP.</FilaVacia>
            )}
          </TableBody>
        </Table>
      )}
    </Panel>
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
    <Panel>
      <PanelTitle title="Tipos de proyecto" />
      {isLoading ? (
        <FilasCargando />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Tipo</TableHead>
              <TableHead className="text-right">Licitaciones</TableHead>
              <TableHead className="text-right">Importe</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {[...tipos]
              .sort((a, b) => b.count - a.count)
              .map((item, idx) => (
                <TableRow key={idx}>
                  <TableCell className="font-medium">{item.tipo}</TableCell>
                  <TableCell numeric>{formatNumber(item.count)}</TableCell>
                  <TableCell numeric>{formatCurrency(item.importe)}</TableCell>
                </TableRow>
              ))}
            {tipos.length === 0 && (
              <FilaVacia columnas={3}>
                Ninguna licitación del ámbito actual tiene tipo de proyecto identificado.
              </FilaVacia>
            )}
          </TableBody>
        </Table>
      )}
    </Panel>
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
    <Panel>
      <PanelTitle title="Códigos CPV con más licitaciones" />
      {isLoading ? (
        <FilasCargando />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>CPV</TableHead>
              <TableHead className="text-right">Licitaciones</TableHead>
              <TableHead className="text-right">Importe</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filas.map((item) => (
              <TableRow key={item.cpv}>
                <TableCell>
                  <Pista contenido={item.cpv_desc}>
                    <span className="block max-w-md truncate">{item.cpv_desc}</span>
                  </Pista>
                </TableCell>
                <TableCell numeric>{formatNumber(item.count)}</TableCell>
                <TableCell numeric>{formatCurrency(item.importe)}</TableCell>
              </TableRow>
            ))}
            {filas.length === 0 && (
              <FilaVacia columnas={3}>Ningún CPV con licitaciones en el ámbito actual.</FilaVacia>
            )}
          </TableBody>
        </Table>
      )}
    </Panel>
  );
}
