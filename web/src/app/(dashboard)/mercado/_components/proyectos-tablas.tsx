"use client";

/**
 * Las tablas de «Proyectos y módulos»: familias y módulos SAP (ordenables, la
 * misma tabla para los dos cortes), tipos de proyecto y códigos CPV.
 *
 * El orden de las ordenables es estado de la tabla: cada una lleva el suyo y
 * entra por licitaciones, de más a menos, como llegan.
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
import { useSortToggle } from "@/hooks/use-sort-toggle";
import { cn, formatCurrency, formatNumber } from "@/lib/utils";

import type { Schemas } from "@/lib/api-types";
import type { FilaCategoria, TipoProyectoRow } from "../_hooks/use-proyectos-modulos-view";

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

type ClaveOrden = keyof FilaCategoria;

/** El nombre entra A→Z; las cifras, de mayor a menor. */
const SENTIDO_INICIAL = (clave: ClaveOrden): "asc" | "desc" => (clave === "nombre" ? "asc" : "desc");

function ordenar(filas: FilaCategoria[], clave: ClaveOrden, sentido: "asc" | "desc"): FilaCategoria[] {
  const signo = sentido === "asc" ? 1 : -1;
  return [...filas].sort((a, b) => {
    const va = a[clave];
    const vb = b[clave];
    return signo * (typeof va === "string" ? va.localeCompare(String(vb)) : va - Number(vb));
  });
}

/**
 * Familias o módulos SAP con su cantidad, su importe y su importe medio,
 * ordenable por cualquiera de las cuatro columnas.
 */
export function TablaCategorias({
  titulo,
  etiqueta,
  columnaNombre,
  filas,
  vacio,
  isLoading,
}: {
  titulo: string;
  /** Nombre accesible de la tabla. */
  etiqueta: string;
  columnaNombre: string;
  filas: FilaCategoria[];
  vacio: string;
  isLoading: boolean;
}) {
  const { sortKey, sortDir, toggleSort } = useSortToggle<ClaveOrden>("count", "desc", SENTIDO_INICIAL);
  const columnas: [ClaveOrden, string][] = [
    ["nombre", columnaNombre],
    ["count", "Licitaciones"],
    ["importe", "Importe total"],
    ["importe_medio", "Importe medio"],
  ];
  const ordenadas = ordenar(filas, sortKey, sortDir);

  return (
    <Panel>
      <PanelTitle title={titulo} />
      {isLoading ? (
        <FilasCargando />
      ) : (
        <Table aria-label={etiqueta}>
          <TableHeader>
            <TableRow>
              {columnas.map(([clave, label]) => {
                const activa = sortKey === clave;
                return (
                  <TableHead
                    key={clave}
                    aria-sort={activa ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
                    className={cn(clave !== "nombre" && "text-right")}
                  >
                    {/* La versal va en el botón: el navegador no se la hereda. */}
                    <button
                      type="button"
                      onClick={() => toggleSort(clave)}
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
            {ordenadas.map((fila) => (
              <TableRow key={fila.nombre}>
                <TableCell className="font-medium">{fila.nombre}</TableCell>
                <TableCell numeric>{formatNumber(fila.count)}</TableCell>
                <TableCell numeric>{formatCurrency(fila.importe)}</TableCell>
                <TableCell numeric>{formatCurrency(fila.importe_medio)}</TableCell>
              </TableRow>
            ))}
            {filas.length === 0 && <FilaVacia columnas={4}>{vacio}</FilaVacia>}
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
