"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { KpiCard } from "@/components/charts/kpi-card";
import dynamic from "next/dynamic";
import { ExportPopover } from "@/components/export-popover";
const GanttChart = dynamic(() => import("@/components/charts/gantt-chart").then(m => ({ default: m.GanttChart })), { ssr: false });
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  formatCurrency,
  formatNumber,
  formatDate,
  truncate,
  cn,
} from "@/lib/utils";
import { Bell,
  Clock,
  AlertTriangle,
  Calendar,
  Target,
  Building2,
  Filter,
} from "lucide-react";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  Cell,
  ReferenceLine,
  Line,
  ComposedChart,
  Legend,
} from "recharts";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

interface PipelineItem {
  id_externo?: string;
  titulo: string;
  organo_contratacion?: string;
  importe?: number;
  fecha_limite?: string;
  dias_restantes?: number;
  estado?: string;
  score?: number;
}

interface HorizonteCount {
  horizonte: string;
  count: number;
  importe: number;
}

interface TrimestreCount {
  trimestre: string;
  count: number;
  importe: number;
}

interface UrgenciaValorPoint {
  id_externo: string;
  titulo?: string;
  dias_restantes: number;
  importe: number;
  es_urgente: boolean;
}

interface PipelineData {
  total_en_plazo: number;
  vencen_7d: number;
  vencen_30d: number;
  upcoming: PipelineItem[];
  por_horizonte: HorizonteCount[];
  por_trimestre: TrimestreCount[];
  urgencia_valor: UrgenciaValorPoint[];
}

interface ForecastEntry {
  id_externo: string;
  titulo?: string | null;
  organo_contratacion?: string | null;
  importe?: number | null;
  fecha_fin_estimada?: string | null;
  dias_hasta_fin?: number | null;
  estado_forecast?: string | null;
  adjudicatarios?: string | null;
  baja_pct?: number | null;
}

interface RetenderingResumen {
  ya_vencido: number;
  menos_3m: number;
  tres_seis_m: number;
  seis_doce_m: number;
  mas_doce_m: number;
}

interface RetenderingData {
  forecast_entries: ForecastEntry[];
  resumen: RetenderingResumen;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function getDiasBadgeVariant(
  dias: number | undefined,
): "destructive" | "secondary" | "outline" {
  if (dias == null) return "secondary";
  if (dias < 7) return "destructive";
  if (dias < 30) return "secondary";
  return "outline";
}

function getDiasColor(dias: number | undefined): string {
  if (dias == null) return "text-muted-foreground";
  if (dias < 7) return "text-red-600 dark:text-red-400";
  if (dias < 30) return "text-yellow-600 dark:text-yellow-400";
  return "text-green-600 dark:text-green-400";
}

function forecastBadgeColor(estado: string | null | undefined) {
  if (!estado) return "secondary" as const;
  const low = estado.toLowerCase();
  if (low.includes("vencido")) return "destructive" as const;
  if (low.includes("menos") || low.includes("<")) return "secondary" as const;
  return "outline" as const;
}

const HORIZON_COLORS: Record<string, string> = {
  "0-7d": "#ef4444",
  "7-30d": "#f97316",
  "30-90d": "#eab308",
  "90+d": "#22c55e",
};

function horizonColor(label: string) {
  for (const [key, color] of Object.entries(HORIZON_COLORS)) {
    if (label.includes(key) || label.toLowerCase().includes(key))
      return color;
  }
  // Try to parse by position
  if (label.includes("7")) return "#ef4444";
  if (label.includes("30")) return "#f97316";
  if (label.includes("90")) return "#eab308";
  return "#22c55e";
}

/* ------------------------------------------------------------------ */
/*  Page                                                              */
/* ------------------------------------------------------------------ */

export default function PipelineAlertasPage() {
  // Local filter state for forecast
  const [horizonteDias, setHorizonteDias] = useState(90);
  const [importeMin, setImporteMin] = useState<string>("");
  const [soloMantenimiento, setSoloMantenimiento] = useState(false);
  const [scoreMin, setScoreMin] = useState(0);

  // Pipeline (global filters)
  const {
    data: pipelineData,
    isLoading: loadingPipeline,
    error: errorPipeline,
  } = useFilteredQuery<PipelineData>(
    ["analytics", "pipeline"],
    "/api/v1/analytics/pipeline",
    { staleTime: 2 * 60 * 1000 },
  );

  // Forecast / retendering (local filters)
  const forecastParams = useMemo(() => {
    const p: Record<string, string> = {
      horizonte_dias: String(horizonteDias),
    };
    if (importeMin) p.importe_min = importeMin;
    if (soloMantenimiento) p.solo_mantenimiento = "true";
    return p;
  }, [horizonteDias, importeMin, soloMantenimiento]);

  const forecastQs = new URLSearchParams(forecastParams).toString();
  const {
    data: forecastData,
    isLoading: loadingForecast,
    error: errorForecast,
  } = useQuery<RetenderingData>({
    queryKey: ["analytics", "forecast", "retendering", forecastParams],
    queryFn: async () => {
      const url = forecastQs
        ? `/api/v1/analytics/forecast/retendering?${forecastQs}`
        : "/api/v1/analytics/forecast/retendering";
      const res = await fetch(url, { credentials: "include" });
      if (!res.ok) throw new Error(`API error: ${res.status}`);
      return res.json();
    },
    staleTime: 5 * 60 * 1000,
  });

  const isLoading = loadingPipeline;
  const error = errorPipeline || errorForecast;

  // Sorted urgent items
  const sortedItems = useMemo(() => {
    if (!pipelineData?.upcoming) return [];
    return [...pipelineData.upcoming].sort(
      (a, b) => (a.dias_restantes ?? 999) - (b.dias_restantes ?? 999),
    );
  }, [pipelineData]);

  // Score-filtered pipeline score_promedio
  const scoreProm = useMemo(() => {
    if (!pipelineData?.upcoming) return 0;
    const withScore = pipelineData.upcoming.filter(
      (i) => i.score != null && i.score >= scoreMin,
    );
    if (withScore.length === 0) return 0;
    return withScore.reduce((s, i) => s + (i.score ?? 0), 0) / withScore.length;
  }, [pipelineData, scoreMin]);

  // Gantt items from forecast
  const ganttItems = useMemo(() => {
    if (!forecastData?.forecast_entries) return [];
    const today = new Date().toISOString().slice(0, 10);
    return forecastData.forecast_entries
      .filter((e) => e.fecha_fin_estimada)
      .slice(0, 30)
      .map((e) => ({
        id: e.id_externo,
        label: truncate(e.titulo ?? e.id_externo, 40),
        start: today,
        end: e.fecha_fin_estimada!,
        color:
          (e.dias_hasta_fin ?? 999) < 90
            ? "#ef4444"
            : (e.dias_hasta_fin ?? 999) < 180
              ? "#f97316"
              : "#22c55e",
      }));
  }, [forecastData]);

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center">
        <p className="text-destructive">Error: {(error as Error).message}</p>
      </div>
    );
  }

  const resumen = forecastData?.resumen;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            Pipeline &amp; Alertas
          </h1>
          <p className="text-muted-foreground">
            Alertas de plazos, forecast de re-licitacion y analisis de pipeline.
          </p>
        </div>
        <ExportPopover endpoint="/api/v1/exports/download" extraParams={{ seccion: "pipeline-alertas" }} />
      </div>

      {/* Pipeline KPIs */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Total en Plazo"
          value={isLoading ? undefined : formatNumber(pipelineData?.total_en_plazo)}
          icon={Clock}
          loading={isLoading}
        />
        <KpiCard
          title="Vencen en 7 dias"
          value={isLoading ? undefined : formatNumber(pipelineData?.vencen_7d)}
          icon={AlertTriangle}
          loading={isLoading}
          className={
            pipelineData?.vencen_7d && pipelineData.vencen_7d > 0
              ? "border-red-200 dark:border-red-900"
              : undefined
          }
        />
        <KpiCard
          title="Vencen en 30 dias"
          value={isLoading ? undefined : formatNumber(pipelineData?.vencen_30d)}
          icon={Calendar}
          loading={isLoading}
          className={
            pipelineData?.vencen_30d && pipelineData.vencen_30d > 0
              ? "border-yellow-200 dark:border-yellow-900"
              : undefined
          }
        />
        <KpiCard
          title="Score Promedio"
          value={
            isLoading
              ? undefined
              : scoreProm > 0
                ? scoreProm.toFixed(1)
                : "-"
          }
          icon={Target}
          loading={isLoading}
        />
      </div>

      {/* Opportunity Funnel */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Funnel de Oportunidades</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[120px] w-full" />
          ) : (
            <div className="space-y-3">
              {[
                {
                  label: "Detectadas (en plazo)",
                  value: pipelineData?.total_en_plazo ?? 0,
                  pct: 100,
                  color: "bg-blue-500",
                },
                {
                  label: "En ventana (30d)",
                  value: pipelineData?.vencen_30d ?? 0,
                  pct:
                    pipelineData?.total_en_plazo
                      ? ((pipelineData.vencen_30d ?? 0) /
                          pipelineData.total_en_plazo) *
                        100
                      : 0,
                  color: "bg-yellow-500",
                },
                {
                  label: "Urgentes (7d)",
                  value: pipelineData?.vencen_7d ?? 0,
                  pct:
                    pipelineData?.total_en_plazo
                      ? ((pipelineData.vencen_7d ?? 0) /
                          pipelineData.total_en_plazo) *
                        100
                      : 0,
                  color: "bg-red-500",
                },
              ].map((stage) => (
                <div key={stage.label} className="space-y-1">
                  <div className="flex justify-between text-sm">
                    <span>{stage.label}</span>
                    <span className="tabular-nums font-medium">
                      {formatNumber(stage.value)}
                    </span>
                  </div>
                  <div className="h-6 w-full rounded bg-muted overflow-hidden">
                    <div
                      className={cn("h-full rounded", stage.color)}
                      style={{
                        width: `${Math.max(stage.pct, 2)}%`,
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Charts Row: Horizon + Quarterly */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Horizon Distribution */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Distribucion por Horizonte
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[260px] w-full" />
            ) : (pipelineData?.por_horizonte?.length ?? 0) > 0 ? (
              <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart
                  data={pipelineData!.por_horizonte}
                  layout="vertical"
                  margin={{ left: 10, right: 20, top: 5, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" />
                  <YAxis type="category" dataKey="horizonte" width={80} tick={{ fontSize: 12 }} />
                  {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                  <Tooltip
                    formatter={(v: any) => formatNumber(v as number)}
                  />
                  <Bar dataKey="count" name="Licitaciones" radius={[0, 4, 4, 0]}>
                    {pipelineData!.por_horizonte.map((entry, i) => (
                      <Cell
                        key={i}
                        fill={horizonColor(entry.horizonte)}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
              </ChartErrorBoundary>
            ) : (
              <p className="py-12 text-center text-muted-foreground">
                Sin datos de horizonte
              </p>
            )}
          </CardContent>
        </Card>

        {/* Quarterly Volume */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Volumen Trimestral</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[260px] w-full" />
            ) : (pipelineData?.por_trimestre?.length ?? 0) > 0 ? (
              <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={260}>
                <ComposedChart
                  data={pipelineData!.por_trimestre}
                  margin={{ left: 10, right: 20, top: 5, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="trimestre" tick={{ fontSize: 11 }} />
                  <YAxis
                    yAxisId="left"
                    tick={{ fontSize: 11 }}
                  />
                  <YAxis
                    yAxisId="right"
                    orientation="right"
                    tick={{ fontSize: 11 }}
                    tickFormatter={(v) => formatCurrency(v)}
                  />
                  {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                  <Tooltip
                    formatter={(v: any, name: any) =>
                      name === "Importe" ? formatCurrency(v as number) : formatNumber(v as number)
                    }
                  />
                  <Legend />
                  <Bar
                    yAxisId="left"
                    dataKey="count"
                    name="Licitaciones"
                    fill="hsl(var(--primary))"
                    radius={[4, 4, 0, 0]}
                  />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="importe"
                    name="Importe"
                    stroke="#f97316"
                    strokeWidth={2}
                    dot={false}
                  />
                </ComposedChart>
              </ResponsiveContainer>
              </ChartErrorBoundary>
            ) : (
              <p className="py-12 text-center text-muted-foreground">
                Sin datos trimestrales
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Urgency x Value Scatter */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            Urgencia vs Valor
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[300px] w-full" />
          ) : (pipelineData?.urgencia_valor?.length ?? 0) > 0 ? (
            <ChartErrorBoundary>
            <ResponsiveContainer width="100%" height={300}>
              <ScatterChart margin={{ left: 10, right: 20, top: 5, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  type="number"
                  dataKey="dias_restantes"
                  name="Dias restantes"
                  tick={{ fontSize: 11 }}
                />
                <YAxis
                  type="number"
                  dataKey="importe"
                  name="Importe"
                  tick={{ fontSize: 11 }}
                  tickFormatter={(v) => formatCurrency(v)}
                />
                {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                <Tooltip
                  formatter={(v: any, name: any) =>
                    name === "Importe" ? formatCurrency(v as number) : formatNumber(v as number)
                  }
                />
                <ReferenceLine
                  x={7}
                  stroke="#ef4444"
                  strokeDasharray="5 5"
                  label={{ value: "7d", fill: "#ef4444", fontSize: 11 }}
                />
                <Scatter
                  data={pipelineData!.urgencia_valor}
                  name="Oportunidades"
                >
                  {pipelineData!.urgencia_valor.map((point, i) => (
                    <Cell
                      key={i}
                      fill={point.es_urgente ? "#ef4444" : "#3b82f6"}
                    />
                  ))}
                </Scatter>
              </ScatterChart>
            </ResponsiveContainer>
              </ChartErrorBoundary>
          ) : (
            <p className="py-12 text-center text-muted-foreground">
              Sin datos de urgencia
            </p>
          )}
        </CardContent>
      </Card>

      {/* Urgent Items List */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Bell className="h-4 w-4" />
            Licitaciones Activas (por urgencia)
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-4">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-24 w-full" />
              ))}
            </div>
          ) : sortedItems.length > 0 ? (
            <div className="space-y-3">
              {sortedItems.map((item, idx) => (
                <div
                  key={item.id_externo ?? idx}
                  className="rounded-lg border p-4 hover:bg-muted/50 transition-colors"
                >
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    <div className="flex-1 min-w-0">
                      <h3 className="text-sm font-medium leading-snug">
                        {truncate(item.titulo, 100)}
                      </h3>
                      {item.organo_contratacion && (
                        <div className="flex items-center gap-1.5 mt-1 text-xs text-muted-foreground">
                          <Building2 className="h-3 w-3 shrink-0" />
                          {truncate(item.organo_contratacion, 60)}
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {item.score != null && (
                        <Badge variant="outline" className="tabular-nums">
                          Score: {item.score.toFixed(1)}
                        </Badge>
                      )}
                      {item.estado && (
                        <Badge variant="secondary">{item.estado}</Badge>
                      )}
                    </div>
                  </div>
                  <Separator className="my-2" />
                  <div className="flex flex-wrap items-center gap-4 text-xs">
                    {item.importe != null && (
                      <span className="tabular-nums font-medium">
                        {formatCurrency(item.importe)}
                      </span>
                    )}
                    {item.fecha_limite && (
                      <span className="text-muted-foreground">
                        Limite: {formatDate(item.fecha_limite)}
                      </span>
                    )}
                    {item.dias_restantes != null && (
                      <Badge variant={getDiasBadgeVariant(item.dias_restantes)}>
                        <span className={getDiasColor(item.dias_restantes)}>
                          {item.dias_restantes < 0
                            ? `Vencido hace ${Math.abs(item.dias_restantes)}d`
                            : item.dias_restantes === 0
                              ? "Vence hoy"
                              : `${item.dias_restantes}d restantes`}
                        </span>
                      </Badge>
                    )}
                  </div>
                </div>
              ))}
              <Separator className="my-2" />
              <p className="text-xs text-muted-foreground">
                {sortedItems.length} licitaciones activas
              </p>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Clock className="h-10 w-10 text-muted-foreground/50 mb-3" />
              <p className="text-muted-foreground">
                No hay licitaciones activas en el pipeline
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ============================================================ */}
      {/*  FORECAST RE-TENDERING SECTION                               */}
      {/* ============================================================ */}
      <Separator />
      <h2 className="text-xl font-semibold tracking-tight">
        Forecast Re-licitacion
      </h2>

      {/* Filter Controls */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Filter className="h-4 w-4" />
            Filtros de Forecast
          </CardTitle>
        </CardHeader>
        <CardContent>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="space-y-2">
              <label className="text-xs font-medium">
                Horizonte: {horizonteDias} dias
              </label>
              <Slider
                value={[horizonteDias]}
                onValueChange={([v]) => setHorizonteDias(v)}
                min={30}
                max={365}
                step={10}
                className="w-full"
              />
            </div>
            <div className="space-y-2">
              <label className="text-xs font-medium">Importe minimo</label>
              <Input
                type="number"
                placeholder="0"
                value={importeMin}
                onChange={(e) => setImporteMin(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <label className="text-xs font-medium">Solo mantenimiento</label>
              <div className="pt-1">
                <Switch
                  checked={soloMantenimiento}
                  onCheckedChange={setSoloMantenimiento}
                  aria-label="Solo mantenimiento"
                />
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-xs font-medium">Score minimo: {scoreMin}</label>
              <Slider
                value={[scoreMin]}
                onValueChange={([v]) => setScoreMin(v)}
                min={0}
                max={100}
                step={5}
                className="w-full"
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Forecast Summary KPIs */}
      {resumen && (
        <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-5">
          {[
            {
              label: "Ya vencido",
              value: resumen.ya_vencido,
              border: "border-red-300 dark:border-red-800",
            },
            {
              label: "<3 meses",
              value: resumen.menos_3m,
              border: "border-orange-300 dark:border-orange-800",
            },
            {
              label: "3-6 meses",
              value: resumen.tres_seis_m,
              border: "border-yellow-300 dark:border-yellow-800",
            },
            {
              label: "6-12 meses",
              value: resumen.seis_doce_m,
              border: "border-blue-300 dark:border-blue-800",
            },
            {
              label: ">12 meses",
              value: resumen.mas_doce_m,
              border: "border-green-300 dark:border-green-800",
            },
          ].map((card) => (
            <Card key={card.label} className={card.border}>
              <CardContent className="p-4 text-center">
                <p className="text-2xl font-bold tabular-nums">
                  {formatNumber(card.value)}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  {card.label}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Gantt Timeline */}
      {ganttItems.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Calendar className="h-4 w-4" />
              Timeline de Re-licitacion (Top 30)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {loadingForecast ? (
              <Skeleton className="h-[400px] w-full" />
            ) : (
              <GanttChart items={ganttItems} height={500} />
            )}
          </CardContent>
        </Card>
      )}

      {/* Forecast Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            Contratos Proximos a Re-licitar
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loadingForecast ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : (forecastData?.forecast_entries?.length ?? 0) > 0 ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="text-left text-muted-foreground">
                    <TableHead>Titulo</TableHead>
                    <TableHead>Organo</TableHead>
                    <TableHead>Importe</TableHead>
                    <TableHead>Fin Estimado</TableHead>
                    <TableHead>Dias</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead>Adjudicatarios</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {forecastData!.forecast_entries.map((entry) => (
                    <TableRow key={entry.id_externo}>
                      <TableCell className="font-medium max-w-[200px] truncate">
                        {truncate(entry.titulo ?? entry.id_externo, 45)}
                      </TableCell>
                      <TableCell className="max-w-[160px] truncate text-muted-foreground">
                        {truncate(entry.organo_contratacion ?? "-", 35)}
                      </TableCell>
                      <TableCell className="tabular-nums">
                        {entry.importe != null
                          ? formatCurrency(entry.importe)
                          : "-"}
                      </TableCell>
                      <TableCell className="tabular-nums text-muted-foreground">
                        {entry.fecha_fin_estimada
                          ? formatDate(entry.fecha_fin_estimada)
                          : "-"}
                      </TableCell>
                      <TableCell className="tabular-nums">
                        <span
                          className={getDiasColor(
                            entry.dias_hasta_fin ?? undefined,
                          )}
                        >
                          {entry.dias_hasta_fin ?? "-"}
                        </span>
                      </TableCell>
                      <TableCell>
                        {entry.estado_forecast && (
                          <Badge
                            variant={forecastBadgeColor(entry.estado_forecast)}
                          >
                            {entry.estado_forecast}
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="max-w-[160px] truncate text-muted-foreground">
                        {truncate(entry.adjudicatarios ?? "-", 35)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <Separator className="my-3" />
              <p className="text-xs text-muted-foreground">
                {forecastData!.forecast_entries.length} contratos en forecast
              </p>
            </div>
          ) : (
            <p className="py-8 text-center text-muted-foreground">
              Sin datos de forecast disponibles
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
