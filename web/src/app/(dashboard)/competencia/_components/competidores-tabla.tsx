"use client";

/**
 * La tabla de competidores: cabecera ordenable, filas y pie con el
 * «mostrando N de M».
 *
 * Va antes que los nueve cortes de gráfico porque es la superficie que los
 * gobierna: antes había que bajar 2.400 px de gráficos para llegar a ella.
 */

import { Panel, PanelEmpty, PanelTitle } from "@/components/console/panel";
import { IndicadorOrden } from "@/components/ui/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import { CABECERA_COLUMNA, Table, TableBody, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn, formatNumber } from "@/lib/utils";

import type { Competitor, SortKey } from "../_hooks/competidores-types";
import { CompetitorRow } from "./competidor-fila";

const TABLE_COLUMNS: { key: SortKey; label: string; numeric?: boolean }[] = [
  { key: "nombre", label: "Nombre" },
  { key: "nif", label: "NIF" },
  { key: "count", label: "Adjudicaciones", numeric: true },
  { key: "importe", label: "Importe", numeric: true },
  { key: "cuota", label: "Cuota %", numeric: true },
  { key: "contratos_por_anio", label: "Contratos/año", numeric: true },
  { key: "importe_medio", label: "Importe medio", numeric: true },
  { key: "baja_media", label: "Baja media %", numeric: true },
  { key: "ofertas_medias", label: "Ofertas medias", numeric: true },
  { key: "pct_monopolio", label: "% sin competencia", numeric: true },
  { key: "pct_top_organo", label: "% órgano principal", numeric: true },
  { key: "ultima", label: "Última adj." },
];

/**
 * Clave estable de fila: las identidades del maestro primero, luego los NIFs y
 * sólo como último recurso el nombre. Un competidor agrupado cambia de nombre
 * al fusionarse; sus ids, no.
 */
function rowKey(c: Competitor, idx: number): string {
  if ((c.empresa_ids?.length ?? 0) > 0) return `ids:${c.empresa_ids!.join("-")}`;
  if (c.nifs?.length) return `nifs:${c.nifs.join("-")}`;
  return `nombre:${c.nombre}:${idx}`;
}

export function CompetidoresTabla({
  filas,
  totalEmpresas,
  isLoading,
  search,
  sortKey,
  sortDir,
  onSort,
  selectedCompanies,
  onToggleCompare,
  onDrillDown,
}: {
  filas: Competitor[];
  /** Universo del que salen las filas visibles, para el pie de la tabla. */
  totalEmpresas: number;
  isLoading: boolean;
  search: string;
  sortKey: SortKey;
  sortDir: "asc" | "desc";
  onSort: (key: SortKey) => void;
  selectedCompanies: string[];
  onToggleCompare: (nombre: string) => void;
  onDrillDown: (competitor: Competitor) => void;
}) {
  return (
    <Panel>
      <PanelTitle title="Todos los competidores" hint="Marca dos empresas para compararlas" />
      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : filas.length > 0 ? (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">
                  <span className="sr-only">Comparar</span>
                </TableHead>
                {TABLE_COLUMNS.map(({ key, label, numeric }) => {
                  const activa = sortKey === key;
                  return (
                    <TableHead
                      key={key}
                      aria-sort={activa ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
                      className={cn("whitespace-nowrap", numeric && "text-right")}
                    >
                      {/* Botón real dentro del `<th>`: foco, Intro y Espacio
                          sin reinventarlos. La versal va en el botón, que no
                          la hereda del `<th>`. */}
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
              {filas.map((c, idx) => (
                <CompetitorRow
                  key={rowKey(c, idx)}
                  competitor={c}
                  selected={selectedCompanies.includes(c.nombre)}
                  onToggleCompare={onToggleCompare}
                  onDrillDown={onDrillDown}
                />
              ))}
            </TableBody>
          </Table>
          <p className="mt-3 border-t border-border/60 pt-3 text-tf-meta text-muted-foreground">
            Mostrando {formatNumber(filas.length)} de {formatNumber(totalEmpresas)} competidores
          </p>
        </>
      ) : (
        <PanelEmpty
          title={search ? "Ningún competidor coincide con la búsqueda" : "Ningún competidor"}
          hint={
            search
              ? "Prueba con otro nombre o NIF."
              : "No hay adjudicaciones en el ámbito actual. Amplía las fechas o quita filtros."
          }
        />
      )}
    </Panel>
  );
}
