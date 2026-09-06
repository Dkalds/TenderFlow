"use client";

import * as React from "react";
import { Search } from "lucide-react";
import { TableVirtuoso, type TableComponents } from "react-virtuoso";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { TableBody, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn, formatNumber } from "@/lib/utils";
import { TOP_OPORTUNIDADES, type RenovacionRow } from "../../_hooks/use-horizonte";
import { CeldasRenovacion } from "./horizonte-fila";

interface RenovacionesRowContext {
  onRowActivate: (licitacionId: string) => void;
}

/**
 * Up to 1000 rows (`limit=1000`) previously rendered fully into the DOM
 * inside a `max-h-[560px] overflow-auto` div (pick-ui-library: virtualize
 * long lists/tables instead). `TableVirtuoso` composes with the existing
 * `ui/table.tsx` primitives via its `components` map — `Table` is written
 * inline (no wrapping div: Virtuoso's own Scroller owns the single
 * scrollable container) and `TableRow` reads the row's `item` from context
 * to wire the same click/keydown-to-navigate behavior the plain `<tr>` had.
 * Defined at module scope (not per-render) per Virtuoso's own guidance —
 * per-render data (the navigate callback) is passed via `context` instead.
 */
function VirtuosoTable(props: React.ComponentProps<"table">) {
  return <table {...props} className="w-full caption-bottom text-sm" />;
}

function VirtuosoTableRow({
  item,
  context,
  ...props
}: React.ComponentProps<"tr"> & { item: RenovacionRow; context?: RenovacionesRowContext }) {
  return (
    <TableRow
      {...props}
      tabIndex={0}
      className="cursor-pointer hover:bg-muted/50"
      onClick={() => context?.onRowActivate(item.licitacion_id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") context?.onRowActivate(item.licitacion_id);
      }}
    />
  );
}

const VirtuosoTableHead = React.forwardRef<HTMLTableSectionElement, React.ComponentProps<"thead">>(
  function VirtuosoTableHead(props, ref) {
    return <TableHeader ref={ref} {...props} className={cn("bg-card", props.className)} />;
  },
);

const renovacionesTableComponents: TableComponents<RenovacionRow, RenovacionesRowContext> = {
  Table: VirtuosoTable,
  TableHead: VirtuosoTableHead,
  TableBody,
  TableRow: VirtuosoTableRow,
};

/**
 * Tabla de contratos que vencen, con su caja de búsqueda.
 *
 * La descripción declara el universo de lo que se está mirando —top N por
 * oportunidad, ordenado en el servidor sobre el dataset completo— porque sin
 * eso la tabla se leería como «todos los contratos que vencen», que es otra
 * cosa. Cuando hay filtro escrito, además dice cuántas filas casan.
 */
export function HorizonteLista({
  items,
  isLoading,
  empresaSearch,
  onEmpresaSearchChange,
  maxScore,
  onAnticipar,
  onAbrirDetalle,
}: {
  items: RenovacionRow[];
  isLoading: boolean;
  empresaSearch: string;
  onEmpresaSearchChange: (valor: string) => void;
  maxScore: number;
  onAnticipar: (licitacionId: string) => void;
  onAbrirDetalle: (licitacionId: string) => void;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <CardTitle>Contratos que vencen</CardTitle>
          <CardDescription>
            Top {formatNumber(TOP_OPORTUNIDADES)} por oportunidad (riesgo × importe × urgencia), ordenado en
            el servidor sobre el dataset completo
            {empresaSearch ? ` · ${formatNumber(items.length)} coinciden con el filtro` : ""}.
          </CardDescription>
        </div>
        <div className="relative w-full sm:w-72">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Filtrar por empresa, órgano o título…"
            value={empresaSearch}
            onChange={(e) => onEmpresaSearchChange(e.target.value)}
            className="pl-8"
          />
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-[400px] w-full" />
        ) : items.length === 0 ? (
          <EmptyState icon={Search} title="Sin resultados" hint="Ningún contrato coincide con el filtro actual." />
        ) : (
          <TableVirtuoso<RenovacionRow, RenovacionesRowContext>
            style={{ height: 560 }}
            data={items}
            computeItemKey={(_index, r) => `${r.licitacion_id}-${r.empresa_id ?? r.empresa}`}
            context={{ onRowActivate: onAbrirDetalle }}
            components={renovacionesTableComponents}
            fixedHeaderContent={() => (
              <TableRow>
                <TableHead>Vence</TableHead>
                <TableHead>Contrato</TableHead>
                <TableHead>Adjudicatario</TableHead>
                <TableHead>Órgano</TableHead>
                <TableHead className="text-right">Importe</TableHead>
                <TableHead className="text-right">Riesgo de cambio</TableHead>
                <TableHead className="text-right">Oportunidad</TableHead>
                <TableHead className="text-right">Acción</TableHead>
              </TableRow>
            )}
            itemContent={(_index, r) => (
              <CeldasRenovacion fila={r} maxScore={maxScore} onAnticipar={onAnticipar} />
            )}
          />
        )}
      </CardContent>
    </Card>
  );
}
