"use client";

import { useState, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { PipelineRoleNav } from "@/components/pipeline-role-nav";
import { KpiCard } from "@/components/charts/kpi-card";
import { ExportPopover } from "@/components/export-popover";
import { EmptyState } from "@/components/ui/empty-state";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  formatCurrency,
  formatNumber,
  formatDate,
  truncate,
  cn,
} from "@/lib/utils";
import {
  Bell,
  BellRing,
  Clock,
  AlertTriangle,
  Calendar,
  Building2,
  Filter,
  Plus,
  Trash2,
  Search,
  TrendingUp,
  ArrowRight,
} from "lucide-react";
import type {
  PipelineResult,
  RetenderingResult,
  ForecastVolumeResult,
} from "@/generated/api";

/* ------------------------------------------------------------------ */
/*  Lazy chart imports                                                 */
/* ------------------------------------------------------------------ */

const GanttChart = dynamic(
  () => import("@/components/charts/gantt-chart").then((m) => ({ default: m.GanttChart })),
  { ssr: false, loading: () => <Skeleton className="h-[420px] w-full rounded-md" /> },
);
const PipelineHorizonChart = dynamic(
  () => import("@/components/charts/pipeline-charts").then((m) => ({ default: m.PipelineHorizonChart })),
  { ssr: false, loading: () => <Skeleton className="h-[260px] w-full rounded-md" /> },
);
const PipelineQuarterlyChart = dynamic(
  () => import("@/components/charts/pipeline-charts").then((m) => ({ default: m.PipelineQuarterlyChart })),
  { ssr: false, loading: () => <Skeleton className="h-[260px] w-full rounded-md" /> },
);
const PipelineUrgencyScatter = dynamic(
  () => import("@/components/charts/pipeline-charts").then((m) => ({ default: m.PipelineUrgencyScatter })),
  { ssr: false, loading: () => <Skeleton className="h-[300px] w-full rounded-md" /> },
);
const PipelineForecastChart = dynamic(
  () => import("@/components/charts/pipeline-charts").then((m) => ({ default: m.PipelineForecastChart })),
  { ssr: false, loading: () => <Skeleton className="h-[300px] w-full rounded-md" /> },
);

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type Frequency = "immediate" | "daily" | "weekly";

interface WatchRule {
  id: number;
  nombre: string | null;
  keyword: string | null;
  cpv: string | null;
  min_importe: number | null;
  ccaa: string | null;
  frequency: Frequency;
  active: boolean;
  match_count: number;
}

const FREQ_LABEL: Record<Frequency, string> = {
  immediate: "Inmediata",
  daily: "Diaria",
  weekly: "Semanal",
};

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Importe abreviado para subtítulos de KPI (1,2 M € / 340 k €). */
function compactEur(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(1).replace(".", ",")} M €`;
  if (abs >= 1_000) return `${Math.round(v / 1_000)} k €`;
  return formatCurrency(v);
}

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

async function apiSend(method: string, url: string, body?: unknown): Promise<unknown> {
  const res = await fetch(url, {
    method,
    credentials: "include",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json().catch(() => null);
}

/* ================================================================== */
/*  Page                                                              */
/* ================================================================== */

export default function PipelineAlertasPage() {
  const router = useRouter();
  const qc = useQueryClient();

  /* ---- Forecast (re-licitación) local filters ---- */
  const [horizonteDias, setHorizonteDias] = useState(90);
  const [importeMin, setImporteMin] = useState<string>("");
  const [soloMantenimiento, setSoloMantenimiento] = useState(false);

  /* ---- Forecast volume metric ---- */
  const [volMetric, setVolMetric] = useState<"count" | "sum">("count");

  /* ---- Cola de cierre: filtros de display (cliente) ---- */
  const [search, setSearch] = useState("");
  const [colaImporteMin, setColaImporteMin] = useState(0);

  /* ---- Alta rápida de alerta ---- */
  const [alertKeyword, setAlertKeyword] = useState("");
  const [alertImporte, setAlertImporte] = useState("");
  const [alertFreq, setAlertFreq] = useState<Frequency>("daily");

  /* ---------------------------------------------------------------- */
  /*  Queries                                                         */
  /* ---------------------------------------------------------------- */

  const {
    data: pipelineData,
    isLoading: loadingPipeline,
    error: errorPipeline,
  } = useFilteredQuery<PipelineResult>(
    ["analytics", "pipeline"],
    "/api/v1/analytics/pipeline",
    { staleTime: 2 * 60 * 1000 },
  );

  const { data: volumeData, isLoading: loadingVolume } =
    useFilteredQuery<ForecastVolumeResult>(
      ["analytics", "forecast", "volume", volMetric],
      "/api/v1/analytics/forecast/volume",
      { staleTime: 5 * 60 * 1000 },
      { months_ahead: "6", metric: volMetric },
    );

  const forecastParams = useMemo(() => {
    const p: Record<string, string> = { horizonte_dias: String(horizonteDias) };
    if (importeMin) p.importe_min = importeMin;
    if (soloMantenimiento) p.solo_mantenimiento = "true";
    return p;
  }, [horizonteDias, importeMin, soloMantenimiento]);

  const {
    data: forecastData,
    isLoading: loadingForecast,
  } = useQuery<RetenderingResult>({
    queryKey: ["analytics", "forecast", "retendering", forecastParams],
    queryFn: async () => {
      const qs = new URLSearchParams(forecastParams).toString();
      const res = await fetch(`/api/v1/analytics/forecast/retendering?${qs}`, {
        credentials: "include",
      });
      if (!res.ok) throw new Error(`API error: ${res.status}`);
      return res.json();
    },
    staleTime: 5 * 60 * 1000,
  });

  /* ---- Alertas (reglas de watchlist server-side) ---- */
  const { data: rules, isLoading: loadingRules } = useQuery<WatchRule[]>({
    queryKey: ["watchlist-rules"],
    queryFn: async () => {
      const data = (await apiSend("GET", "/api/v1/watchlist/rules")) as {
        items?: WatchRule[];
      };
      return data.items ?? [];
    },
    staleTime: 60 * 1000,
  });

  const invalidateRules = () =>
    qc.invalidateQueries({ queryKey: ["watchlist-rules"] });

  const createRule = useMutation({
    mutationFn: (body: Partial<WatchRule>) =>
      apiSend("POST", "/api/v1/watchlist/rules", body),
    onSuccess: invalidateRules,
  });
  const deleteRule = useMutation({
    mutationFn: (id: number) => apiSend("DELETE", `/api/v1/watchlist/rules/${id}`),
    onSuccess: invalidateRules,
  });

  /* ---------------------------------------------------------------- */
  /*  Derived                                                         */
  /* ---------------------------------------------------------------- */

  const activeRules = useMemo(
    () => (rules ?? []).filter((r) => r.active),
    [rules],
  );
  const totalMatches = useMemo(
    () => activeRules.reduce((s, r) => s + (r.match_count ?? 0), 0),
    [activeRules],
  );

  // Cola de cierre — orden por urgencia + filtros de display (cliente).
  const colaItems = useMemo(() => {
    const items = pipelineData?.upcoming ?? [];
    const q = search.trim().toLowerCase();
    return [...items]
      .filter((it) => (colaImporteMin > 0 ? (it.importe ?? 0) >= colaImporteMin : true))
      .filter((it) => {
        if (!q) return true;
        return (
          (it.titulo ?? "").toLowerCase().includes(q) ||
          (it.organo_contratacion ?? "").toLowerCase().includes(q)
        );
      })
      .sort((a, b) => (a.dias_restantes ?? 999) - (b.dias_restantes ?? 999));
  }, [pipelineData, search, colaImporteMin]);

  // Volumen forecast normalizado para el chart.
  const volumeSeries = useMemo(
    () =>
      (volumeData?.series ?? []).map((p) => ({
        mes: p.mes,
        valor: p.valor,
        tipo: p.tipo,
        lower: p.lower,
        upper: p.upper,
      })),
    [volumeData],
  );

  // Gantt de re-licitación.
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

  const handleCreateAlert = () => {
    const kw = alertKeyword.trim();
    const min = alertImporte ? parseFloat(alertImporte) : null;
    if (!kw && min == null) return;
    createRule.mutate({
      nombre: kw || (min ? `Importe ≥ ${compactEur(min)}` : "Alerta de pipeline"),
      keyword: kw || null,
      min_importe: min,
      frequency: alertFreq,
      active: true,
    });
    setAlertKeyword("");
    setAlertImporte("");
    setAlertFreq("daily");
  };

  /* ---------------------------------------------------------------- */
  /*  Render                                                          */
  /* ---------------------------------------------------------------- */

  if (errorPipeline) {
    return (
      <div
        className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center"
        role="alert"
      >
        <p className="text-destructive">Error: {(errorPipeline as Error).message}</p>
      </div>
    );
  }

  const resumen = forecastData?.resumen;
  const hasVolume = volumeSeries.length > 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Pipeline &amp; Alertas</h1>
          <p className="text-muted-foreground">
            Oportunidades activas que están cerrando, alertas suscribibles y
            forecast de re-licitación — todo en una vista.
          </p>
        </div>
        <ExportPopover
          endpoint="/api/v1/exports/download"
          extraParams={{ seccion: "pipeline-alertas" }}
        />
      </div>

      <PipelineRoleNav current="pipeline-alertas" />

      {/* ============================================================ */}
      {/*  KPIs (conteo + valor económico)                            */}
      {/* ============================================================ */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="En plazo"
          value={loadingPipeline ? undefined : formatNumber(pipelineData?.total_en_plazo)}
          subtitle={`${compactEur(pipelineData?.valor_total)} en juego`}
          icon={Clock}
          accent="primary"
          loading={loadingPipeline}
        />
        <KpiCard
          title="Vencen ≤ 7 días"
          value={loadingPipeline ? undefined : formatNumber(pipelineData?.vencen_7d)}
          subtitle={`${compactEur(pipelineData?.valor_7d)} urgente`}
          icon={AlertTriangle}
          accent="hot"
          loading={loadingPipeline}
          className={
            pipelineData?.vencen_7d ? "border-red-200 dark:border-red-900" : undefined
          }
        />
        <KpiCard
          title="Vencen ≤ 30 días"
          value={loadingPipeline ? undefined : formatNumber(pipelineData?.vencen_30d)}
          subtitle={`${compactEur(pipelineData?.valor_30d)} en ventana`}
          icon={Calendar}
          accent="warm"
          loading={loadingPipeline}
          className={
            pipelineData?.vencen_30d ? "border-yellow-200 dark:border-yellow-900" : undefined
          }
        />
        <KpiCard
          title="Alertas activas"
          value={loadingRules ? undefined : formatNumber(activeRules.length)}
          subtitle={
            activeRules.length > 0
              ? `${formatNumber(totalMatches)} coincidencias seguidas`
              : "Sin reglas activas"
          }
          icon={BellRing}
          accent="cold"
          loading={loadingRules}
        />
      </div>

      {/* ============================================================ */}
      {/*  ALERTAS REALES (reglas de watchlist)                       */}
      {/* ============================================================ */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <Bell className="h-4 w-4" />
                Alertas suscribibles
              </CardTitle>
              <CardDescription>
                Reglas server-side: el conteo es real (todo el dataset) y las
                notificaciones se envían según la frecuencia.
              </CardDescription>
            </div>
            <Link
              href="/mi-watchlist"
              className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
            >
              Gestionar en Mi Watchlist
              <ArrowRight className="h-3 w-3" />
            </Link>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Alta rápida */}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="space-y-1">
              <label htmlFor="al-kw" className="text-xs font-medium">
                Palabra clave
              </label>
              <Input
                id="al-kw"
                placeholder="Ej: SAP, S/4HANA…"
                value={alertKeyword}
                onChange={(e) => setAlertKeyword(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleCreateAlert()}
              />
            </div>
            <div className="space-y-1">
              <label htmlFor="al-imp" className="text-xs font-medium">
                Importe mínimo
              </label>
              <Input
                id="al-imp"
                type="number"
                placeholder="Ej: 100000"
                value={alertImporte}
                onChange={(e) => setAlertImporte(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <label htmlFor="al-freq" className="text-xs font-medium">
                Frecuencia
              </label>
              <Select value={alertFreq} onValueChange={(v) => setAlertFreq(v as Frequency)}>
                <SelectTrigger id="al-freq">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="immediate">Inmediata</SelectItem>
                  <SelectItem value="daily">Diaria</SelectItem>
                  <SelectItem value="weekly">Semanal</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-end">
              <Button
                className="w-full"
                onClick={handleCreateAlert}
                disabled={
                  createRule.isPending || (!alertKeyword.trim() && !alertImporte)
                }
              >
                <Plus className="mr-2 h-4 w-4" />
                Crear alerta
              </Button>
            </div>
          </div>

          <Separator />

          {/* Reglas existentes */}
          {loadingRules ? (
            <div className="flex flex-wrap gap-2">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-9 w-40 rounded-full" />
              ))}
            </div>
          ) : (rules?.length ?? 0) === 0 ? (
            <p className="text-sm text-muted-foreground">
              No tienes alertas configuradas. Crea una arriba para que el sistema
              te avise cuando entren licitaciones que cumplan tus criterios.
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {(rules ?? []).map((rule) => (
                <div
                  key={rule.id}
                  className={cn(
                    "group flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm",
                    rule.active ? "bg-muted/40" : "opacity-50",
                  )}
                >
                  <BellRing
                    className={cn(
                      "h-3.5 w-3.5 shrink-0",
                      rule.active ? "text-primary" : "text-muted-foreground",
                    )}
                  />
                  <span className="font-medium">
                    {rule.nombre || rule.keyword || "Regla"}
                  </span>
                  <Badge variant="secondary" className="tabular-nums">
                    {formatNumber(rule.match_count)}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    {FREQ_LABEL[rule.frequency]}
                  </span>
                  <button
                    type="button"
                    aria-label={`Eliminar alerta ${rule.nombre ?? rule.keyword ?? ""}`}
                    className="text-muted-foreground transition-colors hover:text-destructive"
                    onClick={() => deleteRule.mutate(rule.id)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ============================================================ */}
      {/*  ANÁLISIS DEL PIPELINE                                       */}
      {/* ============================================================ */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Distribución por horizonte</CardTitle>
          </CardHeader>
          <CardContent>
            {loadingPipeline ? (
              <Skeleton className="h-[260px] w-full" />
            ) : (pipelineData?.por_horizonte?.length ?? 0) > 0 ? (
              <PipelineHorizonChart data={pipelineData!.por_horizonte} />
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Volumen trimestral</CardTitle>
          </CardHeader>
          <CardContent>
            {loadingPipeline ? (
              <Skeleton className="h-[260px] w-full" />
            ) : (pipelineData?.por_trimestre?.length ?? 0) > 0 ? (
              <PipelineQuarterlyChart data={pipelineData!.por_trimestre} />
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Forecast de volumen (próximos 6 meses) */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="flex items-center gap-2 text-base">
              <TrendingUp className="h-4 w-4" />
              Forecast de volumen (6 meses)
            </CardTitle>
            <div className="flex items-center gap-1" role="group" aria-label="Métrica del forecast">
              <Button
                size="sm"
                variant={volMetric === "count" ? "default" : "outline"}
                onClick={() => setVolMetric("count")}
              >
                Nº licitaciones
              </Button>
              <Button
                size="sm"
                variant={volMetric === "sum" ? "default" : "outline"}
                onClick={() => setVolMetric("sum")}
              >
                Importe
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {loadingVolume ? (
            <Skeleton className="h-[300px] w-full" />
          ) : hasVolume ? (
            <>
              <PipelineForecastChart data={volumeSeries} metric={volMetric} />
              <p className="mt-2 text-xs text-muted-foreground">
                Previsión Holt-Winters / regresión con banda de confianza ~1,5σ.
                Estimación del modelo, no dato observado.
              </p>
            </>
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>

      {/* Urgencia × Valor */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Urgencia vs valor</CardTitle>
        </CardHeader>
        <CardContent>
          {loadingPipeline ? (
            <Skeleton className="h-[300px] w-full" />
          ) : (pipelineData?.urgencia_valor?.length ?? 0) > 0 ? (
            <PipelineUrgencyScatter
              data={pipelineData!.urgencia_valor}
              onPointClick={(id) => router.push(`/detalle?lic=${id}`)}
            />
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>

      {/* ============================================================ */}
      {/*  COLA DE CIERRE (urgentes)                                   */}
      {/* ============================================================ */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Bell className="h-4 w-4" />
              Cola de cierre (por urgencia)
            </CardTitle>
            <div className="flex flex-wrap items-center gap-3">
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  className="h-9 w-48 pl-8"
                  placeholder="Buscar título / órgano…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  aria-label="Buscar en la cola"
                />
              </div>
              <div className="flex w-44 items-center gap-2">
                <span className="whitespace-nowrap text-xs text-muted-foreground">
                  ≥ {compactEur(colaImporteMin)}
                </span>
                <Slider
                  value={[colaImporteMin]}
                  onValueChange={([v]) => setColaImporteMin(v)}
                  min={0}
                  max={1_000_000}
                  step={50_000}
                  aria-label="Importe mínimo"
                />
              </div>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {loadingPipeline ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-24 w-full" />
              ))}
            </div>
          ) : colaItems.length > 0 ? (
            <div className="space-y-3">
              {colaItems.map((item, idx) => (
                <div
                  key={item.id_externo ?? idx}
                  className="rounded-lg border p-4 transition-colors hover:bg-muted/50"
                >
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0 flex-1">
                      <h3 className="text-sm font-medium leading-snug">
                        {item.id_externo ? (
                          <Link
                            href={`/detalle?lic=${item.id_externo}`}
                            className="hover:underline"
                          >
                            {truncate(item.titulo ?? "Sin título", 100)}
                          </Link>
                        ) : (
                          truncate(item.titulo ?? "Sin título", 100)
                        )}
                      </h3>
                      {item.organo_contratacion && (
                        <div className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                          <Building2 className="h-3 w-3 shrink-0" />
                          {truncate(item.organo_contratacion, 60)}
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {item.score != null && (
                        <Badge variant="outline" className="tabular-nums">
                          Score: {item.score}
                        </Badge>
                      )}
                      {item.estado && <Badge variant="secondary">{item.estado}</Badge>}
                    </div>
                  </div>
                  <Separator className="my-2" />
                  <div className="flex flex-wrap items-center gap-4 text-xs">
                    {item.importe != null && (
                      <span className="font-medium tabular-nums">
                        {formatCurrency(item.importe)}
                      </span>
                    )}
                    {item.fecha_limite && (
                      <span className="text-muted-foreground">
                        Límite: {formatDate(item.fecha_limite)}
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
                {colaItems.length} de {pipelineData?.upcoming?.length ?? 0} licitaciones
                {(search || colaImporteMin > 0) && " (filtradas)"}
              </p>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Clock className="mb-3 h-10 w-10 text-muted-foreground/50" />
              <p className="text-muted-foreground">
                {(pipelineData?.upcoming?.length ?? 0) > 0
                  ? "Ninguna licitación cumple los filtros actuales"
                  : "No hay licitaciones activas en el pipeline"}
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ============================================================ */}
      {/*  FORECAST RE-LICITACIÓN                                      */}
      {/* ============================================================ */}
      <Separator />
      <div>
        <h2 className="text-xl font-semibold tracking-tight">Forecast re-licitación</h2>
        <p className="text-sm text-muted-foreground">
          Contratos adjudicados que se acercan a su fin de plazo — oportunidades
          de re-licitación antes de que vuelvan a salir.
        </p>
      </div>

      {/* Filtros de forecast */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Filter className="h-4 w-4" />
            Filtros de forecast
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div className="space-y-2">
              <label className="text-xs font-medium">
                Horizonte: {horizonteDias} días
              </label>
              <Slider
                value={[horizonteDias]}
                onValueChange={([v]) => setHorizonteDias(v)}
                min={30}
                max={365}
                step={10}
              />
            </div>
            <div className="space-y-2">
              <label htmlFor="pa-importe-min" className="text-xs font-medium">
                Importe mínimo
              </label>
              <Input
                id="pa-importe-min"
                type="number"
                placeholder="0"
                value={importeMin}
                onChange={(e) => setImporteMin(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <label htmlFor="pa-solo-mant" className="text-xs font-medium">
                Solo mantenimiento
              </label>
              <div className="pt-1">
                <Switch
                  id="pa-solo-mant"
                  checked={soloMantenimiento}
                  onCheckedChange={setSoloMantenimiento}
                  aria-label="Solo mantenimiento"
                />
              </div>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-3 border-t pt-4">
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                createRule.mutate({
                  nombre: importeMin
                    ? `Re-licitación ≥ ${compactEur(parseFloat(importeMin))}`
                    : "Re-licitación: oportunidades",
                  min_importe: importeMin ? parseFloat(importeMin) : null,
                  frequency: "daily",
                  active: true,
                })
              }
              disabled={createRule.isPending}
            >
              <Bell className="mr-2 h-4 w-4" />
              Alertarme de oportunidades así
            </Button>
            {createRule.isSuccess && (
              <span className="text-xs text-muted-foreground">
                ✓ Alerta creada —{" "}
                <Link href="/mi-watchlist" className="text-primary hover:underline">
                  gestiónala en Mi Watchlist
                </Link>
              </span>
            )}
            {createRule.isError && (
              <span className="text-xs text-destructive">
                No se pudo crear la alerta.
              </span>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Resumen del forecast */}
      {resumen && (
        <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-5">
          {[
            { label: "Ya vencido", value: resumen.ya_vencido, border: "border-red-300 dark:border-red-800" },
            { label: "<3 meses", value: resumen.menos_3m, border: "border-orange-300 dark:border-orange-800" },
            { label: "3-6 meses", value: resumen.tres_seis_m, border: "border-yellow-300 dark:border-yellow-800" },
            { label: "6-12 meses", value: resumen.seis_doce_m, border: "border-blue-300 dark:border-blue-800" },
            { label: ">12 meses", value: resumen.mas_doce_m, border: "border-green-300 dark:border-green-800" },
          ].map((card) => (
            <Card key={card.label} className={card.border}>
              <CardContent className="p-4 text-center">
                <p className="text-2xl font-bold tabular-nums">{formatNumber(card.value)}</p>
                <p className="mt-1 text-xs text-muted-foreground">{card.label}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Gantt */}
      {ganttItems.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Calendar className="h-4 w-4" />
              Timeline de re-licitación (Top 30)
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

      {/* Tabla de forecast */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Contratos próximos a re-licitar</CardTitle>
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
                    <TableHead>Título</TableHead>
                    <TableHead>Órgano</TableHead>
                    <TableHead>Importe</TableHead>
                    <TableHead>Fin estimado</TableHead>
                    <TableHead>Días</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead>Adjudicatarios</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {forecastData!.forecast_entries.map((entry) => (
                    <TableRow key={entry.id_externo}>
                      <TableCell className="max-w-[200px] truncate font-medium">
                        <Link href={`/detalle?lic=${entry.id_externo}`} className="hover:underline">
                          {truncate(entry.titulo ?? entry.id_externo, 45)}
                        </Link>
                      </TableCell>
                      <TableCell className="max-w-[160px] truncate text-muted-foreground">
                        {truncate(entry.organo_contratacion ?? "-", 35)}
                      </TableCell>
                      <TableCell className="tabular-nums">
                        {entry.importe != null ? formatCurrency(entry.importe) : "-"}
                      </TableCell>
                      <TableCell className="tabular-nums text-muted-foreground">
                        {entry.fecha_fin_estimada ? formatDate(entry.fecha_fin_estimada) : "-"}
                      </TableCell>
                      <TableCell className="tabular-nums">
                        <span className={getDiasColor(entry.dias_hasta_fin ?? undefined)}>
                          {entry.dias_hasta_fin ?? "-"}
                        </span>
                      </TableCell>
                      <TableCell>
                        {entry.estado_forecast && (
                          <Badge variant={forecastBadgeColor(entry.estado_forecast)}>
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
