"use client";

/**
 * La tabla completa de competidores: las doce columnas con su cabecera
 * ordenable.
 *
 * Fue la superficie principal de la pantalla; ahora es la otra cara del
 * ranking, a un clic («Tabla completa»). No se pierde nada: quien necesita el
 * NIF, los contratos por año o reordenar por cualquier columna lo tiene aquí,
 * con las mismas dos acciones por fila que el ranking con gráficos.
 */

import { IndicadorOrden } from "@/components/ui/data-table";
import { CABECERA_COLUMNA, Table, TableBody, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

import type { Competitor, SortKey } from "../_hooks/competidores-types";
import { esVigilada } from "../_hooks/vigilados";
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
 * solo como último recurso el nombre. Un competidor agrupado cambia de nombre
 * al fusionarse; sus ids, no.
 */
export function rowKey(c: Competitor, idx: number): string {
  if ((c.empresa_ids?.length ?? 0) > 0) return `ids:${c.empresa_ids!.join("-")}`;
  if (c.nifs?.length) return `nifs:${c.nifs.join("-")}`;
  return `nombre:${c.nombre}:${idx}`;
}

export function CompetidoresTabla({
  filas,
  sortKey,
  sortDir,
  onSort,
  abierta,
  rival,
  vigiladas,
  onAbrir,
  onComparar,
}: {
  filas: Competitor[];
  sortKey: SortKey;
  sortDir: "asc" | "desc";
  onSort: (key: SortKey) => void;
  /** Nombre de la empresa del perfil abierto y de la del cara a cara. */
  abierta: string | null;
  rival: string | null;
  vigiladas: ReadonlySet<number>;
  onAbrir: (nombre: string) => void;
  onComparar: (nombre: string) => void;
}) {
  return (
    <Table>
      <caption className="sr-only">Todos los competidores, con sus doce columnas</caption>
      <TableHeader>
        <TableRow>
          {TABLE_COLUMNS.map(({ key, label, numeric }) => {
            const activa = sortKey === key;
            return (
              <TableHead
                key={key}
                aria-sort={activa ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
                className={cn("whitespace-nowrap", numeric && "text-right")}
              >
                {/* Botón real dentro del `<th>`: foco, Intro y Espacio sin
                    reinventarlos. La versal va en el botón, que no la hereda
                    del `<th>`. */}
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
          <TableHead>
            <span className="sr-only">Comparar</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {filas.map((c, idx) => (
          <CompetitorRow
            key={rowKey(c, idx)}
            competitor={c}
            abierta={c.nombre === abierta}
            comparando={c.nombre === rival}
            vigilada={esVigilada(c, vigiladas)}
            onAbrir={onAbrir}
            onComparar={onComparar}
          />
        ))}
      </TableBody>
    </Table>
  );
}
