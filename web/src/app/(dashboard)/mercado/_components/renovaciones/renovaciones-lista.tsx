"use client";

import * as React from "react";
import { Search } from "lucide-react";
import { TableVirtuoso, type TableComponents } from "react-virtuoso";
import { Panel, PanelEmpty, PanelLoading, PanelTitle } from "@/components/console/panel";
import { TableBody, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn, formatNumber } from "@/lib/utils";
import { TOP_OPORTUNIDADES, type RenovacionRow } from "../../_hooks/use-renovaciones";
import { CeldasRenovacion } from "./renovaciones-fila";

/** Alto de la tabla virtualizada, compartido con el esqueleto y el vacío. */
const ALTO = 560;

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
 * La cabecera declara el universo de lo que se está mirando —top N por
 * oportunidad, ordenado en el servidor sobre el dataset completo— porque sin
 * eso la tabla se leería como «todos los contratos que vencen», que es otra
 * cosa. Cuando hay filtro escrito, además dice cuántas filas casan.
 *
 * La búsqueda filtra **las filas ya servidas**, no vuelve a preguntar: por eso
 * el recuento se enuncia contra el top y no como un total de la ventana.
 */
export function RenovacionesLista({
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
    <Panel>
      <PanelTitle
        title="Contratos que vencen"
        // El `hint` del primitivo se trunca, así que aquí sólo va el recuento
        // del filtro: la declaración del universo va debajo, entera y sin
        // recortar, porque es lo que impide leer la tabla como «todos los
        // contratos que vencen».
        hint={empresaSearch ? `${formatNumber(items.length)} coinciden con el filtro` : undefined}
        actions={
          <div className="flex h-7 w-56 items-center gap-1.5 rounded-md border border-border/70 bg-card px-2 focus-within:border-primary/50">
            <Search className="h-3.5 w-3.5 flex-none text-muted-foreground" aria-hidden="true" />
            <input
              type="search"
              value={empresaSearch}
              onChange={(e) => onEmpresaSearchChange(e.target.value)}
              placeholder="Empresa, órgano o título…"
              aria-label="Filtrar los contratos servidos por empresa, órgano o título"
              className="h-6 min-w-0 flex-1 border-0 bg-transparent text-[12px] text-foreground outline-none placeholder:text-muted-foreground"
            />
          </div>
        }
      />
      <p className="-mt-1.5 mb-3 max-w-[78ch] text-[10.5px] leading-[1.45] text-pretty text-muted-foreground">
        Top {formatNumber(TOP_OPORTUNIDADES)} por oportunidad (riesgo × importe × urgencia). El orden y
        el recorte los hace el servidor sobre el dataset completo, así que esto no son todos los
        contratos que vencen en la ventana: son los {formatNumber(TOP_OPORTUNIDADES)} más accionables.
      </p>
      {isLoading ? (
        <PanelLoading height={ALTO} />
      ) : items.length === 0 ? (
        <PanelEmpty
          message={
            empresaSearch
              ? "Ningún contrato del top servido coincide con el filtro."
              : "Ningún contrato vence en esta ventana. Amplía el horizonte para ver más."
          }
          height={ALTO}
        />
      ) : (
        <TableVirtuoso<RenovacionRow, RenovacionesRowContext>
          style={{ height: ALTO }}
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
    </Panel>
  );
}
