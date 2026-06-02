"use client";

import { useMemo, useState } from "react";
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
import { formatCurrency, formatDate, formatNumber, formatPercent } from "@/lib/utils";
import { getSeriesColor } from "@/lib/chart-colors";
import {
  Cpu,
  Hash,
  Trophy,
  Search,
  Filter,
  TrendingUp,
  Grid3x3,
  Star,
  DollarSign,
  Percent,
  Map as MapIcon,
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
  importe_medio: number;
  pct: number;
  pct_adjudicado: number;
}

interface CrossOrganoItem {
  organo: string;
  tecnologia: string;
  count: number;
}

interface CrossGeoItem {
  ccaa: string;
  tecnologia: string;
  count: number;
}

interface EvolucionItem {
  mes: string;
  tecnologia: string;
  count: number;
  importe: number;
}

interface TecnologiasResponse {
  tecnologias: TecnologiaItem[];
  sin_clasificar: number;
  n_tecnologias: number;
  tecnologia_lider: string | null;
  lider_count: number;
  importe_medio_global: number;
  tasa_adjudicacion_media: number;
  cross_organo: CrossOrganoItem[];
  cross_geo: CrossGeoItem[];
  evolucion_mensual: EvolucionItem[];
}

interface DetalleItem {
  id_externo: string;
  titulo: string | null;
  organo_contratacion: string | null;
  importe: number | null;
  estado: string | null;
  ccaa: string | null;
  fecha_publicacion: string | null;
}

interface DetalleResponse {
  tecnologia: string;
  n: number;
  importe_total: number;
  importe_medio: number;
  items: DetalleItem[];
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

/** Sequential green scale (light -> dark) used to color the "volumen" bars by importe. */
function greenScale(t: number): string {
  const l = 86 - Math.min(Math.max(t, 0), 1) * 52;
  return `hsl(142, 55%, ${l}%)`;
}

/** Sequential blue scale (light -> dark) used to color the "importe" bars by count. */
function blueScale(t: number): string {
  const l = 88 - Math.min(Math.max(t, 0), 1) * 55;
  return `hsl(221, 70%, ${l}%)`;
}

function heatColor(value: number, max: number): string {
  if (value === 0 || max === 0) return "hsl(var(--muted))";
  const l = 92 - (value / max) * 57;
  return `hsl(142, 55%, ${l}%)`;
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

  // Per-technology detail (only when a technology is selected)
  const { data: detalle, isLoading: detalleLoading } = useFilteredQuery<DetalleResponse>(
    ["analytics", "tecnologias", "detail", selectedTech],
    "/api/v1/analytics/tecnologias/detail",
    { enabled: !!selectedTech, staleTime: 5 * 60 * 1000 },
    selectedTech ? { tecnologia: selectedTech } : undefined,
  );

  // Top scored opportunities
  const { data: scoringData } = useFilteredQuery<ScoringResponse>(
    ["analytics", "scoring", "top20"],
    "/api/v1/analytics/scoring",
    { staleTime: 5 * 60 * 1000 },
    { limit: "20" },
  );

  const items = data?.tecnologias ?? [];

  const donutData = useMemo(() => {
    const sorted = [...items].sort((a, b) => b.count - a.count);
    if (sorted.length <= 10) return sorted;
    const top = sorted.slice(0, 9);
    const rest = sorted.slice(9);
    return [
      ...top,
      {
        tecnologia: "Otros",
        count: rest.reduce((s, i) => s + i.count, 0),
        importe: rest.reduce((s, i) => s + i.importe, 0),
        importe_medio: 0,
        pct: rest.reduce((s, i) => s + i.pct, 0),
        pct_adjudicado: 0,
      },
    ];
  }, [items]);

  // Volumen (nº licitaciones), colored by importe
  const volumeBar = useMemo(() => {
    const maxImp = Math.max(1, ...items.map((i) => i.importe));
    return [...items]
      .sort((a, b) => b.count - a.count)
      .slice(0, 15)
      .map((i) => ({ ...i, _color: greenScale(i.importe / maxImp) }))
      .reverse();
  }, [items]);

  // Importe, colored by nº licitaciones
  const importeBar = useMemo(() => {
    const withImporte = items.filter((i) => i.importe > 0);
    const maxN = Math.max(1, ...withImporte.map((i) => i.count));
    return [...withImporte]
      .sort((a, b) => b.importe - a.importe)
      .slice(0, 15)
      .map((i) => ({ ...i, _color: blueScale(i.count / maxN) }))
      .reverse();
  }, [items]);

  const filteredItems = useMemo(() => {
    if (!filter) return items;
    const q = filter.toLowerCase();
    return items.filter((i) => i.tecnologia.toLowerCase().includes(q));
  }, [items, filter]);

  // Monthly evolution split by technology (stacked area)
  const evol = data?.evolucion_mensual ?? [];
  const evolTechs = useMemo(() => {
    const totals = new Map<string, number>();
    for (const e of evol) totals.set(e.tecnologia, (totals.get(e.tecnologia) ?? 0) + e.count);
    return [...totals.entries()].sort((a, b) => b[1] - a[1]).map(([t]) => t);
  }, [evol]);
  const evolData = useMemo(() => {
    const byMes = new Map<string, Record<string, number | string>>();
    for (const e of evol) {
      if (!byMes.has(e.mes)) byMes.set(e.mes, { mes: e.mes });
      const row = byMes.get(e.mes)!;
      const prev = (row[e.tecnologia] as number) ?? 0;
      row[e.tecnologia] = prev + (trendMetric === "importe" ? e.importe : e.count);
    }
    return [...byMes.values()].sort((a, b) => String(a.mes).localeCompare(String(b.mes)));
  }, [evol, trendMetric]);

  // Real tecnologia x organo heatmap (replaces the previous synthetic matrix)
  const heatmap = useMemo(() => {
    const cross = data?.cross_organo ?? [];
    if (cross.length === 0) return null;
    const techTotals = new Map<string, number>();
    const orgTotals = new Map<string, number>();
    for (const c of cross) {
      techTotals.set(c.tecnologia, (techTotals.get(c.tecnologia) ?? 0) + c.count);
      orgTotals.set(c.organo, (orgTotals.get(c.organo) ?? 0) + c.count);
    }
    const techs = [...techTotals.entries()].sort((a, b) => b[1] - a[1]).map(([t]) => t);
    const organos = [...orgTotals.entries()].sort((a, b) => b[1] - a[1]).map(([o]) => o);
    const cell = new Map<string, number>();
    let maxVal = 0;
    for (const c of cross) {
      cell.set(`${c.tecnologia}||${c.organo}`, c.count);
      if (c.count > maxVal) maxVal = c.count;
    }
    return { techs, organos, cell, maxVal };
  }, [data]);

  // Geographic distribution by technology (grouped bar)
  const crossGeo = data?.cross_geo ?? [];
  const geoTechs = useMemo(() => {
    const totals = new Map<string, number>();
    for (const c of crossGeo) totals.set(c.tecnologia, (totals.get(c.tecnologia) ?? 0) + c.count);
    return [...totals.entries()].sort((a, b) => b[1] - a[1]).map(([t]) => t);
  }, [crossGeo]);
  const geoData = useMemo(() => {
    const byCcaa = new Map<string, Record<string, number | string>>();
    const ccaaTotals = new Map<string, number>();
    for (const c of crossGeo) {
      ccaaTotals.set(c.ccaa, (ccaaTotals.get(c.ccaa) ?? 0) + c.count);
      if (!byCcaa.has(c.ccaa)) byCcaa.set(c.ccaa, { ccaa: c.ccaa });
      byCcaa.get(c.ccaa)![c.tecnologia] = c.count;
    }
    return [...byCcaa.values()].sort(
      (a, b) => (ccaaTotals.get(String(b.ccaa)) ?? 0) - (ccaaTotals.get(String(a.ccaa)) ?? 0),
    );
  }, [crossGeo]);

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
            Distribucion, evolucion y cruces por tecnologia detectada.
          </p>
        </div>
        <ExportPopover
          endpoint="/api/v1/exports/download"
          extraParams={{ section: "tecnologias" }}
        />
      </div>

      {/* KPI Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Tecnologias detectadas"
          value={isLoading ? undefined : formatNumber(data?.n_tecnologias ?? 0)}
          subtitle={`${formatNumber(data?.sin_clasificar ?? 0)} sin clasificar`}
          icon={Cpu}
          loading={isLoading}
        />
        <KpiCard
          title="Tecnologia lider"
          value={isLoading ? undefined : (data?.tecnologia_lider ?? "-")}
          subtitle={
            data?.lider_count
              ? `${formatNumber(data.lider_count)} licitaciones`
              : undefined
          }
          icon={Trophy}
          loading={isLoading}
        />
        <KpiCard
          title="Importe medio / tech"
          value={isLoading ? undefined : formatCurrency(data?.importe_medio_global ?? 0)}
          icon={DollarSign}
          loading={isLoading}
        />
        <KpiCard
          title="Tasa adjudicacion"
          value={isLoading ? undefined : formatPercent(data?.tasa_adjudicacion_media ?? 0)}
          subtitle="media por tecnologia"
          icon={Percent}
          loading={isLoading}
        />
      </div>

      {/* Monthly Evolution split by technology */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base">
              <TrendingUp className="h-4 w-4" />
              Evolucion mensual por tecnologia
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
          {isLoading ? (
            <Skeleton className="h-[340px] w-full" />
          ) : evolData.length > 0 && evolTechs.length > 0 ? (
            <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={340}>
                <AreaChart data={evolData}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis dataKey="mes" tick={{ fontSize: 11 }} />
                  <YAxis
                    tick={{ fontSize: 11 }}
                    tickFormatter={(v: number) =>
                      trendMetric === "importe" ? formatCurrency(v) : formatNumber(v)
                    }
                  />
                  <Tooltip
                    formatter={(v, name) => [
                      trendMetric === "importe"
                        ? formatCurrency(v as number)
                        : formatNumber(v as number),
                      name as string,
                    ]}
                  />
                  <Legend />
                  {evolTechs.map((tech, idx) => (
                    <Area
                      key={tech}
                      type="monotone"
                      dataKey={tech}
                      name={tech}
                      stackId="1"
                      stroke={getSeriesColor(idx)}
                      fill={getSeriesColor(idx)}
                      fillOpacity={0.5}
                    />
                  ))}
                </AreaChart>
              </ResponsiveContainer>
            </ChartErrorBoundary>
          ) : (
            <p className="py-12 text-center text-muted-foreground">
              Sin serie temporal disponible
            </p>
          )}
        </CardContent>
      </Card>

      {/* Two complementary bars */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Volumen por tecnologia</CardTitle>
            <p className="text-xs text-muted-foreground">
              Nº de licitaciones (color = importe)
            </p>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[420px] w-full" />
            ) : volumeBar.length > 0 ? (
              <ChartErrorBoundary>
                <ResponsiveContainer width="100%" height={Math.max(300, volumeBar.length * 28)}>
                  <BarChart data={volumeBar} layout="vertical" margin={{ left: 110 }}>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                    <XAxis type="number" tick={{ fontSize: 11 }} />
                    <YAxis dataKey="tecnologia" type="category" width={100} tick={{ fontSize: 11 }} />
                    <Tooltip
                      formatter={(v, _n, p) => [
                        `${formatNumber(v as number)} lic · ${formatCurrency(
                          (p?.payload as TecnologiaItem)?.importe ?? 0,
                        )}`,
                        "Volumen",
                      ]}
                    />
                    <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                      {volumeBar.map((entry, idx) => (
                        <Cell key={idx} fill={entry._color} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </ChartErrorBoundary>
            ) : (
              <p className="py-12 text-center text-muted-foreground">Sin datos</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Importe por tecnologia</CardTitle>
            <p className="text-xs text-muted-foreground">
              Importe acumulado (color = nº licitaciones)
            </p>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[420px] w-full" />
            ) : importeBar.length > 0 ? (
              <ChartErrorBoundary>
                <ResponsiveContainer width="100%" height={Math.max(300, importeBar.length * 28)}>
                  <BarChart data={importeBar} layout="vertical" margin={{ left: 110 }}>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                    <XAxis
                      type="number"
                      tick={{ fontSize: 11 }}
                      tickFormatter={(v: number) => formatCurrency(v)}
                    />
                    <YAxis dataKey="tecnologia" type="category" width={100} tick={{ fontSize: 11 }} />
                    <Tooltip
                      formatter={(v, _n, p) => [
                        `${formatCurrency(v as number)} · ${formatNumber(
                          (p?.payload as TecnologiaItem)?.count ?? 0,
                        )} lic`,
                        "Importe",
                      ]}
                    />
                    <Bar dataKey="importe" radius={[0, 4, 4, 0]}>
                      {importeBar.map((entry, idx) => (
                        <Cell key={idx} fill={entry._color} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </ChartErrorBoundary>
            ) : (
              <p className="py-12 text-center text-muted-foreground">Sin datos</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Donut + Geographic distribution */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Distribucion por cantidad</CardTitle>
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
                      label={({ name, percent }: { name?: string; percent?: number }) =>
                        `${name ?? ""} (${((percent ?? 0) * 100).toFixed(1)}%)`
                      }
                      labelLine={{ strokeWidth: 1 }}
                    >
                      {donutData.map((_, idx) => (
                        <Cell key={idx} fill={getSeriesColor(idx)} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(value) => formatNumber(value as number)} />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              </ChartErrorBoundary>
            ) : (
              <p className="py-12 text-center text-muted-foreground">Sin datos</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <MapIcon className="h-4 w-4" />
              Distribucion geografica por tecnologia
            </CardTitle>
            <p className="text-xs text-muted-foreground">Top 10 CCAA</p>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : geoData.length > 0 && geoTechs.length > 0 ? (
              <ChartErrorBoundary>
                <ResponsiveContainer width="100%" height={Math.max(360, geoData.length * 34)}>
                  <BarChart data={geoData} layout="vertical" margin={{ left: 90 }}>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                    <XAxis type="number" tick={{ fontSize: 11 }} />
                    <YAxis dataKey="ccaa" type="category" width={84} tick={{ fontSize: 10 }} />
                    <Tooltip formatter={(v, name) => [formatNumber(v as number), name as string]} />
                    <Legend />
                    {geoTechs.map((tech, idx) => (
                      <Bar key={tech} dataKey={tech} name={tech} fill={getSeriesColor(idx)} />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </ChartErrorBoundary>
            ) : (
              <p className="py-12 text-center text-muted-foreground">
                Sin datos geograficos
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Real Heatmap: Tech x Organo */}
      {heatmap && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Grid3x3 className="h-4 w-4" />
              Top organos por tecnologia
            </CardTitle>
            <p className="text-xs text-muted-foreground">Nº de licitaciones</p>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <div className="inline-block min-w-full">
                <div
                  className="grid gap-px"
                  style={{
                    gridTemplateColumns: `140px repeat(${heatmap.organos.length}, minmax(80px, 1fr))`,
                  }}
                >
                  <div className="p-1" />
                  {heatmap.organos.map((org) => (
                    <div
                      key={org}
                      className="truncate p-1 text-center text-xs font-medium text-muted-foreground"
                      title={org}
                    >
                      {org.slice(0, 18)}
                    </div>
                  ))}
                </div>
                {heatmap.techs.map((tech) => (
                  <div
                    key={tech}
                    className="grid gap-px"
                    style={{
                      gridTemplateColumns: `140px repeat(${heatmap.organos.length}, minmax(80px, 1fr))`,
                    }}
                  >
                    <div className="truncate p-1 text-xs font-medium" title={tech}>
                      {tech}
                    </div>
                    {heatmap.organos.map((org) => {
                      const val = heatmap.cell.get(`${tech}||${org}`) ?? 0;
                      return (
                        <div
                          key={org}
                          className="flex items-center justify-center rounded p-1 text-xs tabular-nums"
                          style={{
                            backgroundColor: heatColor(val, heatmap.maxVal),
                            color: val > heatmap.maxVal * 0.5 ? "#fff" : "inherit",
                          }}
                          title={`${tech} x ${org}: ${val}`}
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

      {/* Detail by technology */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Filter className="h-4 w-4" />
            Detalle por tecnologia
          </CardTitle>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <Select
              value={selectedTech || "__all__"}
              onValueChange={(v) => setSelectedTech(v === "__all__" ? "" : v)}
            >
              <SelectTrigger className="w-56 text-sm">
                <SelectValue placeholder="Selecciona una tecnologia" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">Selecciona una tecnologia</SelectItem>
                {items.map((t) => (
                  <SelectItem key={t.tecnologia} value={t.tecnologia}>
                    {t.tecnologia}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {selectedTech && (
              <Button variant="ghost" size="sm" onClick={() => setSelectedTech("")}>
                Limpiar
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {!selectedTech ? (
            <p className="py-8 text-center text-muted-foreground">
              Selecciona una tecnologia para ver sus licitaciones.
            </p>
          ) : detalleLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : (
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-3">
                <KpiCard title="Licitaciones" value={formatNumber(detalle?.n ?? 0)} icon={Hash} />
                <KpiCard
                  title="Importe total"
                  value={formatCurrency(detalle?.importe_total ?? 0)}
                  icon={DollarSign}
                />
                <KpiCard
                  title="Importe medio"
                  value={formatCurrency(detalle?.importe_medio ?? 0)}
                  icon={TrendingUp}
                />
              </div>
              <div className="overflow-x-auto">
                <Table className="w-full text-sm">
                  <TableHeader>
                    <TableRow className="border-b text-left">
                      <TableHead className="pb-2 pr-4 font-medium text-muted-foreground">Titulo</TableHead>
                      <TableHead className="pb-2 pr-4 font-medium text-muted-foreground">Organo</TableHead>
                      <TableHead className="pb-2 pr-4 text-right font-medium text-muted-foreground">Importe</TableHead>
                      <TableHead className="pb-2 pr-4 font-medium text-muted-foreground">Estado</TableHead>
                      <TableHead className="pb-2 pr-4 font-medium text-muted-foreground">CCAA</TableHead>
                      <TableHead className="pb-2 font-medium text-muted-foreground">Publicacion</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(detalle?.items ?? []).map((it) => (
                      <TableRow key={it.id_externo} className="border-b border-border/50 hover:bg-muted/50">
                        <TableCell className="max-w-sm py-2 pr-4 font-medium">
                          <span className="line-clamp-2" title={it.titulo ?? ""}>{it.titulo ?? "-"}</span>
                        </TableCell>
                        <TableCell className="max-w-[12rem] truncate py-2 pr-4" title={it.organo_contratacion ?? ""}>
                          {it.organo_contratacion ?? "-"}
                        </TableCell>
                        <TableCell className="py-2 pr-4 text-right tabular-nums">
                          {it.importe != null ? formatCurrency(it.importe) : "-"}
                        </TableCell>
                        <TableCell className="py-2 pr-4">{it.estado ?? "-"}</TableCell>
                        <TableCell className="py-2 pr-4">{it.ccaa ?? "-"}</TableCell>
                        <TableCell className="py-2 tabular-nums">
                          {it.fecha_publicacion ? formatDate(it.fecha_publicacion) : "-"}
                        </TableCell>
                      </TableRow>
                    ))}
                    {(detalle?.items ?? []).length === 0 && (
                      <TableRow>
                        <TableCell colSpan={6} className="py-8 text-center text-muted-foreground">
                          Sin licitaciones
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Aggregated table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Todas las Tecnologias</CardTitle>
          <div className="relative mt-2">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Buscar tecnologia..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="max-w-sm pl-9"
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
                    <TableHead className="pb-2 pr-4 font-medium text-muted-foreground">Tecnologia</TableHead>
                    <TableHead className="pb-2 pr-4 text-right font-medium text-muted-foreground">Cantidad</TableHead>
                    <TableHead className="pb-2 pr-4 text-right font-medium text-muted-foreground">Importe</TableHead>
                    <TableHead className="pb-2 pr-4 text-right font-medium text-muted-foreground">% Adj.</TableHead>
                    <TableHead className="pb-2 text-right font-medium text-muted-foreground">%</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredItems.map((item, idx) => (
                    <TableRow key={idx} className="border-b border-border/50 hover:bg-muted/50">
                      <TableCell className="py-2 pr-4 font-medium">{item.tecnologia}</TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">{formatNumber(item.count)}</TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">{formatCurrency(item.importe)}</TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">{formatPercent(item.pct_adjudicado)}</TableCell>
                      <TableCell className="py-2 text-right tabular-nums">{formatPercent(item.pct)}</TableCell>
                    </TableRow>
                  ))}
                  {filteredItems.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
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
                <div key={idx} className="space-y-1 rounded-lg border border-border p-3">
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-xs tabular-nums text-muted-foreground">{item.id}</span>
                    <Badge variant={item.score >= 80 ? "default" : "secondary"}>{item.score}</Badge>
                  </div>
                  <p className="line-clamp-2 text-sm font-medium" title={item.titulo}>
                    {item.titulo}
                  </p>
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>{formatCurrency(item.importe)}</span>
                    {item.organo_contratacion && (
                      <span className="max-w-[50%] truncate">{item.organo_contratacion}</span>
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
