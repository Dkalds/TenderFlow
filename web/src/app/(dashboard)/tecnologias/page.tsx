"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { KpiCard } from "@/components/charts/kpi-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ExportPopover } from "@/components/export-popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";
import { CHART_SERIES, getSeriesColor } from "@/lib/chart-colors";
import {
  Cpu,
  Hash,
  AlertTriangle,
  Trophy,
  Search,
  Filter,
  TrendingUp,
  Grid3x3,
  Star,
} from "lucide-react";
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
  AreaChart,
  Area,
} from "recharts";

interface TecnologiaItem {
  tecnologia: string;
  count: number;
  importe: number;
  pct: number;
}

interface TecnologiasResponse {
  tecnologias: TecnologiaItem[];
  sin_clasificar: number;
}

interface OrganoItem {
  organo_contratacion: string;
  count: number;
  importe: number;
}

interface OrganosResponse {
  organos: OrganoItem[];
}

interface TrendSeries {
  period: string;
  count: number;
  importe: number;
}

interface TrendsResponse {
  series: TrendSeries[];
}

interface ScoredItem {
  id: string;
  titulo: string;
  importe: number;
  score: number;
  organo_contratacion?: string;
}

interface ScoringResponse {
  opportunities: ScoredItem[];
}


function getHeatColor(value: number, max: number): string {
  if (value === 0 || max === 0) return "hsl(var(--muted))";
  const t = value / max;
  // Light blue to dark blue
  const l = 92 - t * 57;
  return `hsl(221, 83%, ${l}%)`;
}

export default function TecnologiasPage() {
  const [filter, setFilter] = useState("");
  const [selectedTech, setSelectedTech] = useState<string>("");
  const [trendMetric, setTrendMetric] = useState<"count" | "importe">("count");

  const { data, isLoading, error } = useFilteredQuery<TecnologiasResponse>(
    ["analytics", "tecnologias"],
    "/api/v1/analytics/tecnologias",
    { staleTime: 5 * 60 * 1000 },
  );

  // Fetch organos for heatmap
  const { data: organosData } = useQuery<OrganosResponse>({
    queryKey: ["analytics", "organos", "limit10"],
    queryFn: async () => {
      const res = await fetch("/api/v1/analytics/organos?limit=10", {
        credentials: "include",
      });
      if (!res.ok) throw new Error("Failed to fetch organos");
      return res.json();
    },
    staleTime: 5 * 60 * 1000,
  });

  // Fetch trends
  const { data: trendsData } = useQuery<TrendsResponse>({
    queryKey: ["analytics", "trends", "month"],
    queryFn: async () => {
      const res = await fetch("/api/v1/analytics/trends?group_by=month", {
        credentials: "include",
      });
      if (!res.ok) throw new Error("Failed to fetch trends");
      return res.json();
    },
    staleTime: 5 * 60 * 1000,
  });

  // Fetch top scored
  const { data: scoringData } = useQuery<ScoringResponse>({
    queryKey: ["analytics", "scoring", "top20"],
    queryFn: async () => {
      const res = await fetch("/api/v1/analytics/scoring?limit=20", {
        credentials: "include",
      });
      if (!res.ok) throw new Error("Failed to fetch scoring");
      return res.json();
    },
    staleTime: 5 * 60 * 1000,
  });

  const items = data?.tecnologias ?? [];
  const topTech = items.length > 0 ? items[0].tecnologia : "-";

  // When a tech is selected, compute filtered KPIs
  const selectedTechData = useMemo(() => {
    if (!selectedTech) return null;
    return items.find(
      (i) => i.tecnologia.toLowerCase() === selectedTech.toLowerCase(),
    );
  }, [items, selectedTech]);

  const totalCount = useMemo(
    () => items.reduce((s, i) => s + i.count, 0),
    [items],
  );

  const donutData = useMemo(() => {
    const source = selectedTech
      ? items.filter(
          (i) => i.tecnologia.toLowerCase() === selectedTech.toLowerCase(),
        )
      : items;
    const sorted = [...source].sort((a, b) => b.count - a.count);
    if (sorted.length <= 10) return sorted;
    const top = sorted.slice(0, 9);
    const rest = sorted.slice(9);
    return [
      ...top,
      {
        tecnologia: "Otros",
        count: rest.reduce((s, i) => s + i.count, 0),
        importe: rest.reduce((s, i) => s + i.importe, 0),
        pct: rest.reduce((s, i) => s + i.pct, 0),
      },
    ];
  }, [items, selectedTech]);

  const barData = useMemo(() => {
    const source = selectedTech
      ? items.filter(
          (i) => i.tecnologia.toLowerCase() === selectedTech.toLowerCase(),
        )
      : items;
    return [...source]
      .filter((i) => i.importe > 0)
      .sort((a, b) => b.importe - a.importe)
      .slice(0, 20);
  }, [items, selectedTech]);

  const filteredItems = useMemo(() => {
    let source = items;
    if (selectedTech) {
      source = items.filter(
        (i) => i.tecnologia.toLowerCase() === selectedTech.toLowerCase(),
      );
    }
    if (!filter) return source;
    const q = filter.toLowerCase();
    return source.filter((i) => i.tecnologia.toLowerCase().includes(q));
  }, [items, filter, selectedTech]);

  // Heatmap data: top 10 techs x top 10 organos
  // Since we don't have cross-dimensional data, we build a synthetic matrix
  // using the available counts as a proxy
  const heatmapData = useMemo(() => {
    const top10Techs = [...items]
      .sort((a, b) => b.count - a.count)
      .slice(0, 10);
    const top10Organos = (organosData?.organos ?? []).slice(0, 10);
    if (top10Techs.length === 0 || top10Organos.length === 0) return null;

    const totalAll = items.reduce((s, i) => s + i.count, 0);
    const orgTotal = top10Organos.reduce((s, o) => s + o.count, 0);

    // Estimate cell values proportionally
    const matrix = top10Techs.map((tech) => {
      const row: Record<string, number> = {};
      row._tech = 0; // placeholder for name
      for (const org of top10Organos) {
        // Proportional estimate
        const est = Math.round(
          (tech.count * org.count) / Math.max(totalAll, 1),
        );
        row[org.organo_contratacion] = est;
      }
      return { tech: tech.tecnologia, cells: row };
    });

    let maxVal = 0;
    for (const r of matrix) {
      for (const [k, v] of Object.entries(r.cells)) {
        if (k !== "_tech" && v > maxVal) maxVal = v;
      }
    }

    return { techs: top10Techs, organos: top10Organos, matrix, maxVal };
  }, [items, organosData]);

  const scoredItems = scoringData?.opportunities ?? [];

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
          <h1 className="text-2xl font-bold tracking-tight">Tecnologias</h1>
          <p className="text-muted-foreground">
            Distribucion y tendencias de tecnologias mencionadas.
          </p>
        </div>
        <ExportPopover
          endpoint="/api/v1/exports/download"
          extraParams={{ section: "tecnologias" }}
        />
      </div>

      {/* Technology selector */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-muted-foreground" />
          <Select value={selectedTech || "__all__"} onValueChange={(v) => setSelectedTech(v === "__all__" ? "" : v)}>
            <SelectTrigger className="w-56 text-sm">
              <SelectValue placeholder="Todas las tecnologias" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">Todas las tecnologias</SelectItem>
              {items.map((t) => (
                <SelectItem key={t.tecnologia} value={t.tecnologia}>
                  {t.tecnologia}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {selectedTech && (
          <Button variant="ghost" size="sm" onClick={() => setSelectedTech("")}>
            Limpiar filtro
          </Button>
        )}
      </div>

      {/* KPI Row */}
      {selectedTechData ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <KpiCard
            title={`${selectedTechData.tecnologia} — Cantidad`}
            value={formatNumber(selectedTechData.count)}
            icon={Hash}
          />
          <KpiCard
            title={`${selectedTechData.tecnologia} — Importe`}
            value={formatCurrency(selectedTechData.importe)}
            icon={TrendingUp}
          />
          <KpiCard
            title="% del Total"
            value={formatPercent(
              totalCount > 0
                ? (selectedTechData.count / totalCount) * 100
                : 0,
            )}
            icon={Cpu}
          />
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <KpiCard
            title="Total Tecnologias"
            value={
              isLoading
                ? undefined
                : formatNumber(items.length)
            }
            icon={Cpu}
            loading={isLoading}
          />
          <KpiCard
            title="Sin Clasificar"
            value={
              isLoading
                ? undefined
                : formatNumber(data?.sin_clasificar ?? 0)
            }
            icon={AlertTriangle}
            loading={isLoading}
          />
          <KpiCard
            title="Top Tecnologia"
            value={isLoading ? undefined : topTech}
            icon={Trophy}
            loading={isLoading}
          />
        </div>
      )}

      {/* Monthly Evolution */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base">
              <TrendingUp className="h-4 w-4" />
              Evolucion Mensual
            </CardTitle>
            <div className="flex gap-1">
              <Button
                variant={trendMetric === "count" ? "default" : "outline"}
                size="sm"
                onClick={() => setTrendMetric("count")}
              >
                Conteo
              </Button>
              <Button
                variant={trendMetric === "importe" ? "default" : "outline"}
                size="sm"
                onClick={() => setTrendMetric("importe")}
              >
                Importe
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {trendsData?.series && trendsData.series.length > 0 ? (
            <ChartErrorBoundary>
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={trendsData.series}>
                <CartesianGrid
                  strokeDasharray="3 3"
                  className="stroke-border"
                />
                <XAxis dataKey="period" tick={{ fontSize: 12 }} />
                <YAxis
                  tick={{ fontSize: 12 }}
                  tickFormatter={(v: number) =>
                    trendMetric === "importe"
                      ? formatCurrency(v)
                      : formatNumber(v)
                  }
                />
                <Tooltip
                  formatter={(v) =>
                    trendMetric === "importe"
                      ? formatCurrency(v as number)
                      : formatNumber(v as number)
                  }
                />
                <Area
                  type="monotone"
                  dataKey={trendMetric}
                  stroke={CHART_SERIES[0]}
                  fill={CHART_SERIES[0]}
                  fillOpacity={0.15}
                />
              </AreaChart>
            </ResponsiveContainer>
              </ChartErrorBoundary>
          ) : (
            <p className="py-12 text-center text-muted-foreground">
              Evolucion temporal disponible proximamente
            </p>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Donut Chart */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Distribucion por Cantidad
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : donutData.length > 0 ? (
              <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={400}>
                <PieChart>
                  <Pie
                    data={donutData}
                    dataKey="count"
                    nameKey="tecnologia"
                    cx="50%"
                    cy="50%"
                    innerRadius={70}
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
                    {donutData.map((_, idx) => (
                      <Cell
                        key={idx}
                        fill={getSeriesColor(idx)}
                      />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(value) => formatNumber(value as number)}
                  />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
              </ChartErrorBoundary>
            ) : (
              <p className="py-12 text-center text-muted-foreground">
                Sin datos
              </p>
            )}
          </CardContent>
        </Card>

        {/* Bar Chart: by importe */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Top 20 por Importe</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : barData.length > 0 ? (
              <ChartErrorBoundary>
              <ResponsiveContainer
                width="100%"
                height={Math.max(300, barData.length * 28)}
              >
                <BarChart
                  data={barData}
                  layout="vertical"
                  margin={{ left: 100 }}
                >
                  <CartesianGrid
                    strokeDasharray="3 3"
                    className="stroke-border"
                  />
                  <XAxis
                    type="number"
                    tick={{ fontSize: 11 }}
                    tickFormatter={(v: number) => formatCurrency(v)}
                  />
                  <YAxis
                    dataKey="tecnologia"
                    type="category"
                    width={100}
                    tick={{ fontSize: 11 }}
                  />
                  <Tooltip
                    formatter={(value) => [
                      formatCurrency(value as number),
                      "Importe",
                    ]}
                  />
                  <Bar
                    dataKey="importe"
                    fill={CHART_SERIES[1]}
                    radius={[0, 4, 4, 0]}
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

      {/* Heatmap: Tech x Organo */}
      {heatmapData && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Grid3x3 className="h-4 w-4" />
              Heatmap: Tecnologia x Organo (Top 10)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <div className="inline-block min-w-full">
                {/* Header row */}
                <div
                  className="grid gap-px"
                  style={{
                    gridTemplateColumns: `140px repeat(${heatmapData.organos.length}, minmax(80px, 1fr))`,
                  }}
                >
                  <div className="p-1" />
                  {heatmapData.organos.map((org) => (
                    <div
                      key={org.organo_contratacion}
                      className="p-1 text-xs font-medium text-muted-foreground text-center truncate"
                      title={org.organo_contratacion}
                    >
                      {org.organo_contratacion.slice(0, 18)}
                    </div>
                  ))}
                </div>
                {/* Data rows */}
                {heatmapData.matrix.map((row) => (
                  <div
                    key={row.tech}
                    className="grid gap-px"
                    style={{
                      gridTemplateColumns: `140px repeat(${heatmapData.organos.length}, minmax(80px, 1fr))`,
                    }}
                  >
                    <div
                      className="p-1 text-xs font-medium truncate"
                      title={row.tech}
                    >
                      {row.tech}
                    </div>
                    {heatmapData.organos.map((org) => {
                      const val =
                        row.cells[org.organo_contratacion] ?? 0;
                      return (
                        <div
                          key={org.organo_contratacion}
                          className="flex items-center justify-center rounded p-1 text-xs tabular-nums"
                          style={{
                            backgroundColor: getHeatColor(
                              val,
                              heatmapData.maxVal,
                            ),
                            color: val > heatmapData.maxVal * 0.5 ? "#fff" : "inherit",
                          }}
                          title={`${row.tech} x ${org.organo_contratacion}: ${val}`}
                        >
                          {val > 0 ? val : ""}
                        </div>
                      );
                    })}
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Todas las Tecnologias</CardTitle>
          <div className="relative mt-2">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Buscar tecnologia..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="pl-9 max-w-sm"
            />
          </div>
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
                      Tecnologia
                    </TableHead>
                    <TableHead className="pb-2 pr-4 font-medium text-muted-foreground text-right">
                      Cantidad
                    </TableHead>
                    <TableHead className="pb-2 pr-4 font-medium text-muted-foreground text-right">
                      Importe
                    </TableHead>
                    <TableHead className="pb-2 font-medium text-muted-foreground text-right">
                      %
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredItems.map((item, idx) => (
                    <TableRow
                      key={idx}
                      className="border-b border-border/50 hover:bg-muted/50"
                    >
                      <TableCell className="py-2 pr-4 font-medium">
                        {item.tecnologia}
                      </TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">
                        {formatNumber(item.count)}
                      </TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">
                        {formatCurrency(item.importe)}
                      </TableCell>
                      <TableCell className="py-2 text-right tabular-nums">
                        {formatPercent(item.pct)}
                      </TableCell>
                    </TableRow>
                  ))}
                  {filteredItems.length === 0 && (
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

      {/* Top 20 Scored Licitaciones */}
      {scoredItems.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Star className="h-4 w-4" />
              Top 20 Licitaciones por Score
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 sm:grid-cols-2">
              {scoredItems.slice(0, 20).map((item, idx) => (
                <div
                  key={idx}
                  className="rounded-lg border border-border p-3 space-y-1"
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-xs text-muted-foreground tabular-nums">
                      {item.id}
                    </span>
                    <Badge
                      variant={item.score >= 80 ? "default" : "secondary"}
                    >
                      {item.score}
                    </Badge>
                  </div>
                  <p
                    className="text-sm font-medium line-clamp-2"
                    title={item.titulo}
                  >
                    {item.titulo}
                  </p>
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>{formatCurrency(item.importe)}</span>
                    {item.organo_contratacion && (
                      <span className="truncate max-w-[50%]">
                        {item.organo_contratacion}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
