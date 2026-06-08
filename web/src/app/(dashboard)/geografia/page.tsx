"use client";
import { EmptyState } from "@/components/ui/empty-state";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { KpiCard } from "@/components/charts/kpi-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { Button } from "@/components/ui/button";
import { ExportPopover } from "@/components/export-popover";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
const SpainMap = dynamic(() => import("@/components/charts/spain-map").then(m => ({ default: m.SpainMap })), { ssr: false, loading: () => <Skeleton className="h-[420px] w-full rounded-md" /> });
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";
import { CHART_SERIES, getSeriesColor } from "@/lib/chart-colors";
import { MapPin, Hash, Trophy, ArrowUpDown, ArrowUp, ArrowDown, DollarSign, Map } from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";

interface GeoItem {
  ccaa: string;
  count: number;
  importe: number;
  pct: number;
}

interface GeographyResponse {
  by_ccaa: GeoItem[];
}

interface LicitacionItem {
  provincia?: string;
  importe?: number;
}

interface LicitacionesResponse {
  items: LicitacionItem[];
}


type SortKey = "ccaa" | "count" | "importe" | "pct";
type SortDir = "asc" | "desc";
type ProvSortKey = "provincia" | "count" | "importe";

export default function GeografiaPage() {
  const [sortKey, setSortKey] = useState<SortKey>("count");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [provSortKey, setProvSortKey] = useState<ProvSortKey>("count");
  const [provSortDir, setProvSortDir] = useState<SortDir>("desc");
  const [mapMetric, setMapMetric] = useState<"count" | "importe">("count");

  const { data, isLoading, error } = useFilteredQuery<GeographyResponse>(
    ["analytics", "geography"],
    "/api/v1/analytics/geography",
    { staleTime: 5 * 60 * 1000 },
  );

  // Fetch licitaciones for province aggregation
  const { data: licData, isLoading: licLoading } =
    useQuery<LicitacionesResponse>({
      queryKey: ["licitaciones", "provinces"],
      queryFn: async () => {
        const res = await fetch("/api/v1/licitaciones?limit=500", {
          credentials: "include",
        });
        if (!res.ok) throw new Error("Failed to fetch licitaciones");
        return res.json();
      },
      staleTime: 5 * 60 * 1000,
    });

  const items = data?.by_ccaa ?? [];

  const topCcaa = items.length > 0 ? items[0].ccaa : "-";
  const top3Concentration = useMemo(() => {
    if (items.length === 0) return 0;
    const total = items.reduce((s, i) => s + i.count, 0);
    const top3 = items.slice(0, 3).reduce((s, i) => s + i.count, 0);
    return total > 0 ? (top3 / total) * 100 : 0;
  }, [items]);

  // CCAA with highest average ticket
  const ccaaMayorTicket = useMemo(() => {
    if (items.length === 0) return "-";
    let best = items[0];
    let bestRatio = best.count > 0 ? best.importe / best.count : 0;
    for (const item of items) {
      if (item.count === 0) continue;
      const ratio = item.importe / item.count;
      if (ratio > bestRatio) {
        best = item;
        bestRatio = ratio;
      }
    }
    return best.ccaa;
  }, [items]);

  const mapData = useMemo(
    () => items.map((i) => ({ ccaa: i.ccaa, value: i[mapMetric] })),
    [items, mapMetric],
  );

  const barData = useMemo(
    () => [...items].sort((a, b) => b.count - a.count),
    [items],
  );

  const pieData = useMemo(() => {
    const sorted = [...items].sort((a, b) => b.importe - a.importe);
    if (sorted.length <= 10) return sorted;
    const top = sorted.slice(0, 9);
    const rest = sorted.slice(9);
    const otherImporte = rest.reduce((s, i) => s + i.importe, 0);
    return [
      ...top,
      { ccaa: "Otros", count: 0, importe: otherImporte, pct: 0 },
    ];
  }, [items]);

  const sortedItems = useMemo(() => {
    const sorted = [...items];
    sorted.sort((a, b) => {
      const aVal = a[sortKey];
      const bVal = b[sortKey];
      if (typeof aVal === "string" && typeof bVal === "string") {
        return sortDir === "asc"
          ? aVal.localeCompare(bVal)
          : bVal.localeCompare(aVal);
      }
      return sortDir === "asc"
        ? (aVal as number) - (bVal as number)
        : (bVal as number) - (aVal as number);
    });
    return sorted;
  }, [items, sortKey, sortDir]);

  // Province aggregation
  const provinciaData = useMemo(() => {
    const lics = licData?.items ?? [];
    const agg: Record<string, { count: number; importe: number }> = {};
    for (const lic of lics) {
      if (!lic.provincia) continue;
      const prov = lic.provincia;
      if (!agg[prov]) agg[prov] = { count: 0, importe: 0 };
      agg[prov].count += 1;
      agg[prov].importe += lic.importe ?? 0;
    }
    return Object.entries(agg).map(([provincia, vals]) => ({
      provincia,
      count: vals.count,
      importe: vals.importe,
    }));
  }, [licData]);

  const sortedProvincias = useMemo(() => {
    const sorted = [...provinciaData];
    sorted.sort((a, b) => {
      if (provSortKey === "provincia") {
        return provSortDir === "asc"
          ? a.provincia.localeCompare(b.provincia)
          : b.provincia.localeCompare(a.provincia);
      }
      const aVal = a[provSortKey] as number;
      const bVal = b[provSortKey] as number;
      return provSortDir === "asc" ? aVal - bVal : bVal - aVal;
    });
    return sorted;
  }, [provinciaData, provSortKey, provSortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  function toggleProvSort(key: ProvSortKey) {
    if (provSortKey === key) {
      setProvSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setProvSortKey(key);
      setProvSortDir("desc");
    }
  }

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center" role="alert">
        <p className="text-destructive">Error: {(error as Error).message}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Geografia</h1>
          <p className="text-muted-foreground">
            Distribucion geografica por Comunidad Autonoma.
          </p>
        </div>
        <ExportPopover
          endpoint="/api/v1/exports/download"
          extraParams={{ section: "geografia" }}
        />
      </div>

      {/* KPI Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="CCAA Mas Activa"
          value={isLoading ? undefined : topCcaa}
          icon={Trophy}
          loading={isLoading}
        />
        <KpiCard
          title="Concentracion Top 3"
          value={isLoading ? undefined : formatPercent(top3Concentration)}
          subtitle="del total"
          icon={MapPin}
          loading={isLoading}
        />
        <KpiCard
          title="Total CCAAs"
          value={isLoading ? undefined : formatNumber(items.length)}
          icon={Hash}
          loading={isLoading}
        />
        <KpiCard
          title="Mayor Ticket Medio"
          value={isLoading ? undefined : ccaaMayorTicket}
          subtitle="CCAA con mayor importe/licitacion"
          icon={DollarSign}
          loading={isLoading}
        />
      </div>

      {/* Choropleth Map */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base">
              <Map className="h-4 w-4" />
              Mapa por {mapMetric === "count" ? "Licitaciones" : "Importe"}
            </CardTitle>
          <div className="flex items-center gap-1 rounded-lg border p-0.5">
              <Button
                size="sm"
                variant={mapMetric === "count" ? "default" : "ghost"}
                className="h-7 px-3 text-xs"
                onClick={() => setMapMetric("count")}
              >
                Licitaciones
              </Button>
              <Button
                size="sm"
                variant={mapMetric === "importe" ? "default" : "ghost"}
                className="h-7 px-3 text-xs"
                onClick={() => setMapMetric("importe")}
              >
                Importe €
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[500px] w-full" />
          ) : (
            <SpainMap
              data={mapData}
              metric={mapMetric === "count" ? "Licitaciones" : "Importe €"}
              height={480}
            />
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Horizontal Bar Chart */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">CCAAs por Cantidad</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : barData.length > 0 ? (
              <ChartErrorBoundary>
              <ResponsiveContainer
                width="100%"
                height={Math.max(300, barData.length * 30)}
              >
                <BarChart
                  data={barData}
                  layout="vertical"
                  margin={{ left: 120 }}
                >
                  <CartesianGrid
                    strokeDasharray="3 3"
                    className="stroke-border"
                  />
                  <XAxis type="number" tick={{ fontSize: 12 }} />
                  <YAxis
                    dataKey="ccaa"
                    type="category"
                    width={120}
                    tick={{ fontSize: 12 }}
                  />
                  <Tooltip
                    formatter={(value) => [
                      formatNumber(value as number),
                      "Licitaciones",
                    ]}
                  />
                  <Bar
                    dataKey="count"
                    fill={CHART_SERIES[0]}
                    radius={[0, 4, 4, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
              </ChartErrorBoundary>
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>

        {/* Pie Chart */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Distribucion por Importe
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : pieData.length > 0 ? (
              <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={400}>
                <PieChart>
                  <Pie
                    data={pieData}
                    dataKey="importe"
                    nameKey="ccaa"
                    cx="50%"
                    cy="50%"
                    outerRadius={140}
                    label={({
                      name,
                      percent,
                    }: {
                      name?: string;
                      percent?: number;
                    }) =>
                      `${name ?? ""} (${((percent ?? 0) * 100).toFixed(1)}%)`
                    }
                    labelLine={{ strokeWidth: 1 }}
                  >
                    {pieData.map((_, idx) => (
                      <Cell
                        key={idx}
                        fill={getSeriesColor(idx)}
                      />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(value) => formatCurrency(value as number)}
                  />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
              </ChartErrorBoundary>
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>
      </div>

      {/* CCAA Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Todas las CCAAs</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table className="w-full text-sm">
                <TableHeader>
                  <TableRow className="border-b text-left">
                    {(
                      [
                        ["ccaa", "CCAA"],
                        ["count", "Cantidad"],
                        ["importe", "Importe"],
                        ["pct", "%"],
                      ] as [SortKey, string][]
                    ).map(([key, label]) => (
                      <TableHead
                        key={key}
                        className={`pb-2 pr-4 font-medium text-muted-foreground ${key !== "ccaa" ? "text-right" : ""}`}
                      >
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-auto p-0 font-medium text-muted-foreground hover:text-foreground"
                          onClick={() => toggleSort(key)}
                        >
                          {label}
                          {sortKey === key ? (
                            sortDir === "asc" ? (
                              <ArrowUp className="ml-1 h-3 w-3 text-primary" />
                            ) : (
                              <ArrowDown className="ml-1 h-3 w-3 text-primary" />
                            )
                          ) : (
                            <ArrowUpDown className="ml-1 h-3 w-3 opacity-40" />
                          )}
                        </Button>
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedItems.map((item, idx) => (
                    <TableRow
                      key={idx}
                      className="border-b border-border/50 hover:bg-muted/50"
                    >
                      <TableCell className="py-2 pr-4 font-medium">{item.ccaa}</TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">
                        {formatNumber(item.count)}
                      </TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">
                        {formatCurrency(item.importe)}
                      </TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">
                        {formatPercent(item.pct)}
                      </TableCell>
                    </TableRow>
                  ))}
                  {sortedItems.length === 0 && (
                    <TableRow>
                      <TableCell
                        colSpan={4}
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

      {/* Provinces Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Provincias</CardTitle>
        </CardHeader>
        <CardContent>
          {licLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : sortedProvincias.length > 0 ? (
            <div className="overflow-x-auto">
              <Table className="w-full text-sm">
                <TableHeader>
                  <TableRow className="border-b text-left">
                    {(
                      [
                        ["provincia", "Provincia"],
                        ["count", "Cantidad"],
                        ["importe", "Importe"],
                      ] as [ProvSortKey, string][]
                    ).map(([key, label]) => (
                      <TableHead
                        key={key}
                        className={`pb-2 pr-4 font-medium text-muted-foreground ${key !== "provincia" ? "text-right" : ""}`}
                      >
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-auto p-0 font-medium text-muted-foreground hover:text-foreground"
                          onClick={() => toggleProvSort(key)}
                        >
                          {label}
                          {provSortKey === key ? (
                            provSortDir === "asc" ? (
                              <ArrowUp className="ml-1 h-3 w-3 text-primary" />
                            ) : (
                              <ArrowDown className="ml-1 h-3 w-3 text-primary" />
                            )
                          ) : (
                            <ArrowUpDown className="ml-1 h-3 w-3 opacity-40" />
                          )}
                        </Button>
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedProvincias.map((item, idx) => (
                    <TableRow
                      key={idx}
                      className="border-b border-border/50 hover:bg-muted/50"
                    >
                      <TableCell className="py-2 pr-4 font-medium">
                        {item.provincia}
                      </TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">
                        {formatNumber(item.count)}
                      </TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">
                        {formatCurrency(item.importe)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <p className="py-8 text-center text-muted-foreground">
              Sin datos de provincia
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
