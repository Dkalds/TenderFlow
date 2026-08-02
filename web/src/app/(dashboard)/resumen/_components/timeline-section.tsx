"use client";

import Link from "next/link";
import {
  ArrowUpDown,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
} from "lucide-react";
import {
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status-badge";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { CHART_SERIES } from "@/lib/chart-colors";
import { cn, formatCurrency, formatDate, truncate } from "@/lib/utils";
import type { TimelineItem } from "./types";
import { ITEMS_PER_PAGE } from "./types";

/**
 * Publicaciones del periodo: el scatter y la tabla que lo desglosa.
 *
 * Son dos tarjetas apiladas, no una rejilla de dos columnas: con seis columnas
 * fijas la del título resolvía a cero y el texto desaparecía. La tabla conserva
 * sus siete columnas ordenables y su paginación de diez.
 */

const COLUMNS: {
  key: keyof TimelineItem;
  label: string;
  width: string;
  align?: "right";
}[] = [
  { key: "titulo", label: "Título", width: "auto" },
  { key: "organo_contratacion", label: "Órgano", width: "160px" },
  { key: "ccaa", label: "CCAA", width: "104px" },
  { key: "tipo_contrato", label: "Tipo", width: "104px" },
  { key: "importe", label: "Importe", width: "108px", align: "right" },
  { key: "fecha_publicacion", label: "Fecha", width: "84px" },
  { key: "estado", label: "Estado", width: "104px" },
];

interface TimelineSectionProps {
  scatterData: { x: number; y: number; z: number; titulo: string; estado: string; fill: string }[];
  sortedPubs: TimelineItem[];
  isLoading: boolean;
  pubPage: number;
  setPubPage: (fn: (p: number) => number) => void;
  pubSortKey: keyof TimelineItem;
  pubSortDir: "asc" | "desc";
  togglePubSort: (key: keyof TimelineItem) => void;
}

function PanelTitle({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="flex items-baseline gap-2.5">
      <h3 className="text-[12.5px] font-semibold">{title}</h3>
      <span className="text-[10.5px] text-muted-foreground">{hint}</span>
    </div>
  );
}

export function TimelineSection({
  scatterData,
  sortedPubs,
  isLoading,
  pubPage,
  setPubPage,
  pubSortKey,
  pubSortDir,
  togglePubSort,
}: TimelineSectionProps) {
  const totalPubPages = Math.max(1, Math.ceil(sortedPubs.length / ITEMS_PER_PAGE));
  const pagedPubs = sortedPubs.slice(pubPage * ITEMS_PER_PAGE, (pubPage + 1) * ITEMS_PER_PAGE);

  const pageButton =
    "tf-pressable grid h-6 w-6 place-items-center rounded-md border border-border/70 text-muted-foreground transition-colors duration-140 ease-out hover:text-foreground disabled:cursor-default disabled:opacity-35";

  return (
    <div className="mb-5.5 flex flex-col gap-3.5">
      <div className="rounded-xl border border-border/60 bg-card/70 px-4 py-3.5">
        <PanelTitle title="Publicaciones en el periodo" hint="fecha × importe · color por estado" />
        <p className="mb-3.5 mt-1 text-[10.5px] leading-[1.5] text-muted-foreground">
          Cada punto es una licitación publicada. El tamaño también es el importe.
        </p>
        {isLoading ? (
          <Skeleton className="h-[300px] w-full rounded-lg" />
        ) : scatterData.length > 0 ? (
          <ChartErrorBoundary>
            <ResponsiveContainer width="100%" height={300}>
              <ScatterChart accessibilityLayer margin={{ top: 10, right: 10, bottom: 10, left: 10 }}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis
                  dataKey="x"
                  type="number"
                  domain={["dataMin", "dataMax"]}
                  tickFormatter={(value: number) =>
                    new Date(value).toLocaleDateString("es-ES", { month: "short", day: "numeric" })
                  }
                  tick={{ fontSize: 11 }}
                  name="Fecha"
                />
                <YAxis
                  dataKey="y"
                  type="number"
                  tickFormatter={(value: number) => formatCurrency(value)}
                  tick={{ fontSize: 11 }}
                  name="Importe"
                  width={80}
                />
                <ZAxis dataKey="z" range={[30, 250]} />
                <Tooltip
                  content={({ payload }) => {
                    if (!payload?.[0]) return null;
                    const point = payload[0].payload as (typeof scatterData)[0];
                    return (
                      <div className="rounded-md border border-border bg-popover p-2 text-xs shadow">
                        <p className="font-medium">{truncate(point.titulo, 50)}</p>
                        <p className="tf-tnum font-mono">{formatCurrency(point.y)}</p>
                        <p className="text-muted-foreground">{point.estado}</p>
                      </div>
                    );
                  }}
                />
                <Scatter data={scatterData} fill={CHART_SERIES[0]}>
                  {scatterData.map((entry, index) => (
                    <Cell key={index} fill={entry.fill} />
                  ))}
                </Scatter>
              </ScatterChart>
            </ResponsiveContainer>
          </ChartErrorBoundary>
        ) : (
          <div className="rounded-[10px] border border-dashed border-border/60 px-4 py-9 text-center">
            <p className="text-[11.5px] leading-[1.5] text-muted-foreground">
              Sin publicaciones en la ventana seleccionada.
            </p>
          </div>
        )}
      </div>

      <div className="rounded-xl border border-border/60 bg-card/70 px-4 py-3.5">
        <div className="mb-2.5 flex items-center gap-2.5">
          <PanelTitle title="Últimas publicaciones" hint="ordena por cualquier columna" />
          <div className="flex-1" />
          <span className="tf-tnum text-[10.5px] text-muted-foreground">
            {sortedPubs.length === 0
              ? "—"
              : `${pubPage * ITEMS_PER_PAGE + 1}–${Math.min(
                  (pubPage + 1) * ITEMS_PER_PAGE,
                  sortedPubs.length,
                )} de ${sortedPubs.length}`}
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full table-fixed border-collapse">
            <colgroup>
              {COLUMNS.map((column) => (
                <col key={column.key} style={{ width: column.width }} />
              ))}
            </colgroup>
            <thead>
              <tr className="border-b border-border/70">
                {COLUMNS.map((column) => {
                  const active = pubSortKey === column.key;
                  return (
                    <th
                      key={column.key}
                      scope="col"
                      aria-sort={
                        active ? (pubSortDir === "asc" ? "ascending" : "descending") : "none"
                      }
                      className={cn(
                        "pb-2 font-mono text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground",
                        column.align === "right" ? "text-right" : "text-left",
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => togglePubSort(column.key)}
                        className={cn(
                          "inline-flex items-center gap-1 rounded px-1 py-0.5 transition-colors duration-140 ease-out hover:text-foreground",
                          active && "text-primary",
                        )}
                      >
                        {column.label}
                        {active ? (
                          pubSortDir === "asc" ? (
                            <ChevronUp className="h-3 w-3" aria-hidden="true" />
                          ) : (
                            <ChevronDown className="h-3 w-3" aria-hidden="true" />
                          )
                        ) : (
                          <ArrowUpDown className="h-3 w-3 opacity-30" aria-hidden="true" />
                        )}
                      </button>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {isLoading
                ? Array.from({ length: 6 }, (_, index) => (
                    <tr key={index}>
                      <td colSpan={COLUMNS.length} className="py-1.5">
                        <Skeleton className="h-5 w-full rounded" />
                      </td>
                    </tr>
                  ))
                : pagedPubs.map((item) => (
                    <tr key={item.id_externo} className="border-b border-border/25">
                      <td className="px-1 py-1.5">
                        <Link
                          href={`/detalle?lic=${encodeURIComponent(item.id_externo)}`}
                          className="block truncate text-[11.5px] font-medium leading-[1.4] hover:underline"
                        >
                          {item.titulo}
                        </Link>
                      </td>
                      <td className="truncate px-1 text-[11px] text-muted-foreground">
                        {item.organo_contratacion ?? "—"}
                      </td>
                      <td className="truncate px-1 text-[11px] text-muted-foreground">
                        {item.ccaa ?? "—"}
                      </td>
                      <td className="truncate px-1 text-[11px] text-muted-foreground">
                        {item.tipo_contrato ?? "—"}
                      </td>
                      <td className="tf-tnum px-1 text-right font-mono text-[11px] font-semibold whitespace-nowrap">
                        {formatCurrency(item.importe)}
                      </td>
                      <td className="px-1 font-mono text-[10.5px] text-muted-foreground whitespace-nowrap">
                        {formatDate(item.fecha_publicacion)}
                      </td>
                      <td className="px-1">
                        <StatusBadge
                          value={item.estado}
                          kind="estado"
                          className="text-[10.5px]"
                        />
                      </td>
                    </tr>
                  ))}
            </tbody>
          </table>
        </div>

        {!isLoading && pagedPubs.length === 0 && (
          <div className="px-4 py-11 text-center">
            <p className="text-[11.5px] leading-[1.5] text-muted-foreground">
              Sin publicaciones que mostrar.
            </p>
          </div>
        )}

        {sortedPubs.length > ITEMS_PER_PAGE && (
          <nav
            aria-label="Paginación de publicaciones"
            className="mt-2.5 flex items-center gap-2 border-t border-border/40 pt-2.5"
          >
            <div className="flex-1" />
            <button
              type="button"
              aria-label="Página anterior"
              className={pageButton}
              disabled={pubPage === 0}
              onClick={() => setPubPage((page) => Math.max(0, page - 1))}
            >
              <ChevronLeft className="h-3 w-3" aria-hidden="true" />
            </button>
            <span className="tf-tnum font-mono text-[10.5px] text-muted-foreground">
              {pubPage + 1} / {totalPubPages}
            </span>
            <button
              type="button"
              aria-label="Página siguiente"
              className={pageButton}
              disabled={pubPage >= totalPubPages - 1}
              onClick={() => setPubPage((page) => Math.min(totalPubPages - 1, page + 1))}
            >
              <ChevronRight className="h-3 w-3" aria-hidden="true" />
            </button>
          </nav>
        )}
      </div>
    </div>
  );
}
