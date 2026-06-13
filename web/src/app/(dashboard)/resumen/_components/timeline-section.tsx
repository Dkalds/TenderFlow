"use client";

import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn, formatCurrency, formatDate, truncate } from "@/lib/utils";
import { CHART_SERIES } from "@/lib/chart-colors";
import { ChevronLeft, ChevronRight, ChevronUp, ChevronDown, ArrowUpDown } from "lucide-react";
import {
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  Cell,
  XAxis,
  YAxis,
  ZAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";
import type { TimelineItem } from "./types";
import { ITEMS_PER_PAGE } from "./types";

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

  return (
    <>
      {/* Timeline scatter */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Timeline de Publicaciones</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[380px] w-full" />
          ) : scatterData.length > 0 ? (
            <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={380}>
                <ScatterChart margin={{ top: 10, right: 10, bottom: 10, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis
                    dataKey="x"
                    type="number"
                    domain={["dataMin", "dataMax"]}
                    tickFormatter={(v: number) =>
                      new Date(v).toLocaleDateString("es-ES", { month: "short", day: "numeric" })
                    }
                    tick={{ fontSize: 12 }}
                    name="Fecha"
                  />
                  <YAxis
                    dataKey="y"
                    type="number"
                    tickFormatter={(v: number) => formatCurrency(v)}
                    tick={{ fontSize: 12 }}
                    name="Importe"
                    width={80}
                  />
                  <ZAxis dataKey="z" range={[30, 250]} />
                  <Tooltip
                    content={({ payload }) => {
                      if (!payload?.[0]) return null;
                      const d = payload[0].payload as (typeof scatterData)[0];
                      return (
                        <div className="rounded bg-popover p-2 text-xs shadow border border-border">
                          <p className="font-medium">{truncate(d.titulo, 50)}</p>
                          <p>{formatCurrency(d.y)}</p>
                          <p className="text-muted-foreground">{d.estado}</p>
                        </div>
                      );
                    }}
                  />
                  <Scatter data={scatterData} fill={CHART_SERIES[0]}>
                    {scatterData.map((entry, idx) => (
                      <Cell key={idx} fill={entry.fill} />
                    ))}
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
            </ChartErrorBoundary>
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>

      {/* Últimas Publicaciones (paginated) */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">Ultimas Publicaciones</CardTitle>
            {sortedPubs.length > ITEMS_PER_PAGE && (
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  disabled={pubPage === 0}
                  onClick={() => setPubPage((p) => Math.max(0, p - 1))}
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <span className="text-xs text-muted-foreground tabular-nums">
                  {pubPage + 1} / {totalPubPages}
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  disabled={pubPage >= totalPubPages - 1}
                  onClick={() => setPubPage((p) => Math.min(totalPubPages - 1, p + 1))}
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : pagedPubs.length > 0 ? (
            <div className="overflow-x-auto">
              <Table className="table-fixed">
                <TableHeader>
                  <TableRow>
                    {(
                      [
                        { key: "titulo" as const, label: "Titulo", width: "w-[280px]", align: "" },
                        { key: "organo_contratacion" as const, label: "Organo", width: "w-[200px]", align: "" },
                        { key: "ccaa" as const, label: "CCAA", width: "w-[110px]", align: "" },
                        { key: "tipo_contrato" as const, label: "Tipo", width: "w-[120px]", align: "" },
                        { key: "importe" as const, label: "Importe", width: "w-[120px]", align: "text-right" },
                        { key: "fecha_publicacion" as const, label: "Fecha", width: "w-[100px]", align: "" },
                        { key: "estado" as const, label: "Estado", width: "w-[100px]", align: "" },
                      ] as const
                    ).map((col) => (
                      <TableHead
                        key={col.key}
                        className={cn(
                          "select-none cursor-pointer overflow-hidden resize-x",
                          col.width,
                          col.align,
                        )}
                        onClick={() => togglePubSort(col.key)}
                      >
                        <span className="inline-flex items-center gap-1">
                          {col.label}
                          {pubSortKey === col.key ? (
                            pubSortDir === "asc" ? (
                              <ChevronUp className="h-3 w-3" />
                            ) : (
                              <ChevronDown className="h-3 w-3" />
                            )
                          ) : (
                            <ArrowUpDown className="h-3 w-3 opacity-30" />
                          )}
                        </span>
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pagedPubs.map((item) => (
                    <TableRow key={item.id_externo} className="cursor-pointer hover:bg-muted/50">
                      <TableCell>
                        <Link
                          href={`/detalle?lic=${item.id_externo}`}
                          className="text-sm font-medium hover:underline text-primary"
                        >
                          {item.titulo}
                        </Link>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground max-w-[200px] truncate">
                        {item.organo_contratacion ?? "—"}
                      </TableCell>
                      <TableCell className="text-xs">{item.ccaa ?? "—"}</TableCell>
                      <TableCell className="text-xs">{item.tipo_contrato ?? "—"}</TableCell>
                      <TableCell className="text-right text-sm font-medium tabular-nums whitespace-nowrap">
                        {formatCurrency(item.importe)}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                        {formatDate(item.fecha_publicacion)}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-xs">
                          {item.estado}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>
    </>
  );
}
