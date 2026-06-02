"use client";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useFilters } from "@/lib/filters";
import { KpiCard } from "@/components/charts/kpi-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { Badge } from "@/components/ui/badge";
import { SearchAutocomplete } from "@/components/ui/search-autocomplete";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { ExportPopover } from "@/components/export-popover";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";
import { CHART_SERIES, getSeriesColor } from "@/lib/chart-colors";
import { TreemapContent } from "@/components/charts/treemap-content";
import {
  Building2,
  Hash,
  Trophy,
  BarChart3,
  Search,
  Clock,
  Users,
  TrendingUp,
  X,
} from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
const Treemap = dynamic(() => import("recharts").then(m => ({ default: m.Treemap })), { ssr: false });

interface OrganoItem {
  organo_contratacion: string;
  count: number;
  importe: number;
  pct: number;
  ccaa?: string;
}

interface OrganosResponse {
  organos: OrganoItem[];
  total_organos: number;
}

interface OrganoDetailResponse {
  total_licitaciones: number;
  importe_total: number;
  pct_adjudicado: number;
  lead_time_medio: number;
  top_adjudicatarios: { nombre: string; count: number; importe: number }[];
  estacionalidad: { mes: number; count: number }[];
  top_scored: {
    id: string;
    titulo: string;
    importe: number;
    score: number;
  }[];
}


const MONTH_LABELS = [
  "Ene",
  "Feb",
  "Mar",
  "Abr",
  "May",
  "Jun",
  "Jul",
  "Ago",
  "Sep",
  "Oct",
  "Nov",
  "Dic",
];

export default function OrganosPage() {
  const [filter, setFilter] = useState("");
  const [selectedOrgano, setSelectedOrgano] = useState<string | null>(null);

  const { data, isLoading, error } = useFilteredQuery<OrganosResponse>(
    ["analytics", "organos"],
    "/api/v1/analytics/organos",
    { staleTime: 5 * 60 * 1000 },
  );

  const { data: detailData, isLoading: detailLoading } =
    useQuery<OrganoDetailResponse>({
      queryKey: ["analytics", "organos", selectedOrgano],
      queryFn: async () => {
        const res = await fetch(
          `/api/v1/analytics/organos/${encodeURIComponent(selectedOrgano!)}`,
          { credentials: "include" },
        );
        if (!res.ok) throw new Error(`API error: ${res.status}`);
        return res.json();
      },
      enabled: !!selectedOrgano,
      staleTime: 5 * 60 * 1000,
    });

  const items = data?.organos ?? [];

  const top10Concentration = useMemo(() => {
    if (items.length === 0) return 0;
    const totalCount = items.reduce((s, i) => s + i.count, 0);
    const top10Count = items.slice(0, 10).reduce((s, i) => s + i.count, 0);
    return totalCount > 0 ? (top10Count / totalCount) * 100 : 0;
  }, [items]);

  const totalImporte = useMemo(
    () => items.reduce((s, i) => s + i.importe, 0),
    [items],
  );

  const topOrgano = items.length > 0 ? items[0].organo_contratacion : "-";

  // Client-side text filter applied to charts + table
  const filteredItems = useMemo(() => {
    if (!filter) return items;
    const q = filter.toLowerCase();
    return items.filter(
      (i) =>
        i.organo_contratacion.toLowerCase().includes(q) ||
        (i.ccaa && i.ccaa.toLowerCase().includes(q)),
    );
  }, [items, filter]);

  const top20 = useMemo(() => filteredItems.slice(0, 20), [filteredItems]);

  const top15ByImporte = useMemo(
    () => [...filteredItems].sort((a, b) => b.importe - a.importe).slice(0, 15),
    [filteredItems],
  );

  const treemapData = useMemo(
    () =>
      filteredItems
        .filter((i) => i.importe > 0)
        .slice(0, 30)
        .map((i) => ({
          name: i.organo_contratacion,
          size: i.importe,
        })),
    [filteredItems],
  );

  function handleOrganoClick(organo: string) {
    setSelectedOrgano(organo);
  }

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center">
        <p className="text-destructive">Error: {(error as Error).message}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Organos</h1>
          <p className="text-muted-foreground">
            Ranking de organos de contratacion.
          </p>
        </div>
        <ExportPopover
          endpoint="/api/v1/exports/download"
          extraParams={{ section: "organos" }}
        />
      </div>

      {/* Search filter — affects charts + table */}
      <SearchAutocomplete
        className="max-w-sm"
        placeholder="Buscar organo o CCAA..."
        value={filter}
        onChange={setFilter}
        suggestions={[
          ...(data?.organos?.map((i) => i.organo_contratacion) ?? []),
          ...[...new Set(data?.organos?.map((i) => i.ccaa).filter((c): c is string => c != null) ?? [])],
        ]}
        leftIcon={<Search className="h-4 w-4" />}
        inputClassName="pl-9"
      />

      {/* KPI Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Total Organos"
          value={
            isLoading
              ? undefined
              : formatNumber(data?.total_organos ?? items.length)
          }
          icon={Building2}
          loading={isLoading}
        />
        <KpiCard
          title="Concentracion Top 10"
          value={isLoading ? undefined : formatPercent(top10Concentration)}
          subtitle="del total de licitaciones"
          icon={Hash}
          loading={isLoading}
        />
        <KpiCard
          title="Importe Total"
          value={isLoading ? undefined : formatCurrency(totalImporte)}
          icon={TrendingUp}
          loading={isLoading}
        />
        <KpiCard
          title="Top Organo"
          value={
            isLoading
              ? undefined
              : topOrgano.length > 40
                ? topOrgano.slice(0, 40) + "..."
                : topOrgano
          }
          icon={Trophy}
          loading={isLoading}
        />
      </div>

      {/* Top charts: by count + by importe */}
      <div className="grid gap-6 lg:grid-cols-2">
      {/* Horizontal Bar Chart: Top 20 by count */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <BarChart3 className="h-4 w-4" />
            Top 20 Organos por Cantidad
            {filter && (
              <Badge variant="secondary" className="ml-2 text-xs">
                filtrado
              </Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[500px] w-full" />
          ) : top20.length > 0 ? (
            <ChartErrorBoundary>
            <ResponsiveContainer
              width="100%"
              height={Math.max(400, top20.length * 28)}
            >
              <BarChart
                data={top20}
                layout="vertical"
                margin={{ left: 200 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  className="stroke-border"
                />
                <XAxis type="number" tick={{ fontSize: 12 }} />
                <YAxis
                  dataKey="organo_contratacion"
                  type="category"
                  width={200}
                  tick={{ fontSize: 12 }}
                  tickFormatter={(v: string) =>
                    v.length > 35 ? v.slice(0, 35) + "..." : v
                  }
                />
                <Tooltip
                  formatter={(value) => [
                    formatNumber(value as number),
                    "Licitaciones",
                  ]}
                  labelFormatter={(label) => label}
                />
                <Bar
                  dataKey="count"
                  fill={CHART_SERIES[0]}
                  radius={[0, 4, 4, 0]}
                  className="cursor-pointer"
                  onClick={(_data, idx) => {
                    if (top20[idx]) handleOrganoClick(top20[idx].organo_contratacion);
                  }}
                />
              </BarChart>
            </ResponsiveContainer>
              </ChartErrorBoundary>
          ) : (
            <p className="py-12 text-center text-muted-foreground">
              Sin datos
            </p>
          )}
        </CardContent>
      </Card>

      {/* Horizontal Bar Chart: Top 15 by importe */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <BarChart3 className="h-4 w-4" />
            Top 15 Organos por Importe
            {filter && (
              <Badge variant="secondary" className="ml-2 text-xs">
                filtrado
              </Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[500px] w-full" />
          ) : top15ByImporte.length > 0 ? (
            <ChartErrorBoundary>
            <ResponsiveContainer
              width="100%"
              height={Math.max(400, top15ByImporte.length * 28)}
            >
              <BarChart
                data={top15ByImporte}
                layout="vertical"
                margin={{ left: 200 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  className="stroke-border"
                />
                <XAxis type="number" tick={{ fontSize: 12 }} tickFormatter={(v: number) => formatCurrency(v)} />
                <YAxis
                  dataKey="organo_contratacion"
                  type="category"
                  width={200}
                  tick={{ fontSize: 12 }}
                  tickFormatter={(v: string) =>
                    v.length > 35 ? v.slice(0, 35) + "..." : v
                  }
                />
                <Tooltip
                  formatter={(value) => [
                    formatCurrency(value as number),
                    "Importe",
                  ]}
                  labelFormatter={(label) => label}
                />
                <Bar
                  dataKey="importe"
                  fill={CHART_SERIES[1]}
                  radius={[0, 4, 4, 0]}
                  className="cursor-pointer"
                  onClick={(_data, idx) => {
                    if (top15ByImporte[idx]) handleOrganoClick(top15ByImporte[idx].organo_contratacion);
                  }}
                />
              </BarChart>
            </ResponsiveContainer>
              </ChartErrorBoundary>
          ) : (
            <p className="py-12 text-center text-muted-foreground">
              Sin datos
            </p>
          )}
        </CardContent>
      </Card>
      </div>

      {/* Treemap: by importe */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            Organos por Importe
            {filter && (
              <Badge variant="secondary" className="ml-2 text-xs">
                filtrado
              </Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[400px] w-full" />
          ) : treemapData.length > 0 ? (
            <ChartErrorBoundary>
            <ResponsiveContainer width="100%" height={400}>
              <Treemap
                data={treemapData}
                dataKey="size"
                nameKey="name"
                content={<TreemapContent formatValue={(v) => formatCurrency(v)} />}
              />
            </ResponsiveContainer>
              </ChartErrorBoundary>
          ) : (
            <p className="py-12 text-center text-muted-foreground">
              Sin datos de importe
            </p>
          )}
        </CardContent>
      </Card>

      {/* Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Listado Completo</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table className="w-full text-sm">
                <TableHeader>
                  <TableRow className="border-b text-left">
                    <TableHead className="pb-2 pr-4 font-medium text-muted-foreground">
                      Organo
                    </TableHead>
                    <TableHead className="pb-2 pr-4 font-medium text-muted-foreground text-right">
                      Cantidad
                    </TableHead>
                    <TableHead className="pb-2 pr-4 font-medium text-muted-foreground text-right">
                      Importe
                    </TableHead>
                    <TableHead className="pb-2 pr-4 font-medium text-muted-foreground text-right">
                      %
                    </TableHead>
                    <TableHead className="pb-2 font-medium text-muted-foreground">
                      CCAA
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredItems.map((item, idx) => (
                    <TableRow
                      key={idx}
                      className="border-b border-border/50 hover:bg-muted/50 cursor-pointer"
                      tabIndex={0}
                      role="row"
                      onClick={() =>
                        handleOrganoClick(item.organo_contratacion)
                      }
                      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") handleOrganoClick(item.organo_contratacion); }}
                    >
                      <TableCell
                        className="py-2 pr-4 max-w-xs truncate"
                        title={item.organo_contratacion}
                      >
                        {item.organo_contratacion}
                      </TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">
                        {formatNumber(item.count)}
                      </TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">
                        {formatCurrency(item.importe)}
                      </TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">
                        {formatPercent(item.pct)}
                      </TableCell>
                      <TableCell className="py-2">
                        {item.ccaa ? (
                          <Badge variant="secondary">{item.ccaa}</Badge>
                        ) : (
                          "-"
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                  {filteredItems.length === 0 && (
                    <TableRow>
                      <TableCell
                        colSpan={5}
                        className="py-8 text-center text-muted-foreground"
                      >
                        Sin resultados
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Drill-down Sheet */}
      <Sheet
        open={!!selectedOrgano}
        onOpenChange={(open) => !open && setSelectedOrgano(null)}
      >
        <SheetContent className="w-full sm:max-w-xl overflow-y-auto">
          <SheetHeader>
            <SheetTitle className="text-lg leading-tight">
              {selectedOrgano}
            </SheetTitle>
          </SheetHeader>

          {detailLoading ? (
            <div className="mt-6 space-y-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-20 w-full" />
              ))}
            </div>
          ) : detailData ? (
            <div className="mt-6 space-y-6">
              {/* Top adjudicatario highlight */}
              {detailData.top_adjudicatarios?.[0] && (
                <div className="rounded-lg border bg-primary/5 p-3">
                  <p className="text-xs text-muted-foreground">Principal Adjudicatario</p>
                  <p className="font-semibold text-sm">{detailData.top_adjudicatarios[0].nombre}</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    {formatNumber(detailData.top_adjudicatarios[0].count)} adj. &middot; {formatCurrency(detailData.top_adjudicatarios[0].importe)}
                  </p>
                </div>
              )}

              {/* Detail KPIs */}
              <div className="grid grid-cols-2 gap-3">
                <KpiCard
                  title="Licitaciones"
                  value={formatNumber(detailData.total_licitaciones)}
                  icon={Hash}
                />
                <KpiCard
                  title="Importe Total"
                  value={formatCurrency(detailData.importe_total)}
                  icon={TrendingUp}
                />
                <KpiCard
                  title="% Adjudicado"
                  value={formatPercent(detailData.pct_adjudicado)}
                  icon={Trophy}
                />
                <KpiCard
                  title="Lead Time Medio"
                  value={`${Math.round(detailData.lead_time_medio)} dias`}
                  icon={Clock}
                />
              </div>

              {/* Top adjudicatarios */}
              {detailData.top_adjudicatarios?.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-sm">
                      <Users className="h-4 w-4" />
                      Top Adjudicatarios
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-2">
                      {detailData.top_adjudicatarios
                        .slice(0, 10)
                        .map((adj, i) => (
                          <div
                            key={i}
                            className="flex items-center justify-between text-sm"
                          >
                            <span className="truncate max-w-[60%]">
                              {adj.nombre}
                            </span>
                            <span className="tabular-nums text-muted-foreground">
                              {formatNumber(adj.count)} &middot;{" "}
                              {formatCurrency(adj.importe)}
                            </span>
                          </div>
                        ))}
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Estacionalidad */}
              {detailData.estacionalidad?.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm">Estacionalidad</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ChartErrorBoundary>
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={detailData.estacionalidad}>
                        <CartesianGrid
                          strokeDasharray="3 3"
                          className="stroke-border"
                        />
                         <XAxis
                          dataKey="mes"
                          tick={{ fontSize: 12 }}
                          tickFormatter={(m: number) =>
                            MONTH_LABELS[m - 1] ?? String(m)
                          }
                        />
                        <YAxis tick={{ fontSize: 12 }} />
                        <Tooltip
                          labelFormatter={(m) =>
                            MONTH_LABELS[(m as number) - 1] ?? String(m)
                          }
                          formatter={(v) => [
                            formatNumber(v as number),
                            "Licitaciones",
                          ]}
                        />
                        <Bar
                          dataKey="count"
                          fill={CHART_SERIES[0]}
                          radius={[4, 4, 0, 0]}
                        />
                      </BarChart>
                    </ResponsiveContainer>
              </ChartErrorBoundary>
                  </CardContent>
                </Card>
              )}

              {/* Top 30 scored */}
              {detailData.top_scored?.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm">
                      Top {detailData.top_scored.length} por Score
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="overflow-x-auto">
                      <Table className="w-full text-xs">
                        <TableHeader>
                          <TableRow className="border-b text-left">
                            <TableHead className="pb-1 pr-2 font-medium text-muted-foreground">
                              ID
                            </TableHead>
                            <TableHead className="pb-1 pr-2 font-medium text-muted-foreground">
                              Titulo
                            </TableHead>
                            <TableHead className="pb-1 pr-2 font-medium text-muted-foreground text-right">
                              Importe
                            </TableHead>
                            <TableHead className="pb-1 font-medium text-muted-foreground text-right">
                              Score
                            </TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {detailData.top_scored.slice(0, 30).map((s, i) => (
                            <TableRow
                              key={i}
                              className="border-b border-border/50"
                            >
                              <TableCell className="py-1 pr-2 tabular-nums">
                                {s.id}
                              </TableCell>
                              <TableCell
                                className="py-1 pr-2 max-w-[200px] truncate"
                                title={s.titulo}
                              >
                                {s.titulo}
                              </TableCell>
                              <TableCell className="py-1 pr-2 text-right tabular-nums">
                                {formatCurrency(s.importe)}
                              </TableCell>
                              <TableCell className="py-1 text-right">
                                <Badge
                                  variant={
                                    s.score >= 80
                                      ? "default"
                                      : "secondary"
                                  }
                                >
                                  {s.score}
                                </Badge>
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>
          ) : (
            <p className="mt-6 text-sm text-muted-foreground">
              Sin datos del organo.
            </p>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
