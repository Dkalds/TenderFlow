"use client";

import { useQuery } from "@tanstack/react-query";
import { KpiCard } from "@/components/charts/kpi-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { t } from "@/lib/i18n";
import { formatCurrency, formatNumber, truncate } from "@/lib/utils";
import type { AnalyticsOverview } from "@/generated/api";
import {
  BarChart3,
  Building2,
  DollarSign,
  TrendingDown,
  TrendingUp,
  Hash,
  Calendar,
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
  AreaChart,
  Area,
} from "recharts";

const CHART_COLORS = [
  "hsl(221, 83%, 53%)",
  "hsl(160, 60%, 45%)",
  "hsl(30, 80%, 55%)",
  "hsl(280, 65%, 60%)",
  "hsl(340, 75%, 55%)",
  "hsl(200, 70%, 50%)",
  "hsl(120, 50%, 45%)",
  "hsl(45, 85%, 50%)",
];

async function fetchOverview(params?: Record<string, string>): Promise<AnalyticsOverview> {
  const searchParams = new URLSearchParams(params);
  const res = await fetch(`/api/v1/analytics/overview?${searchParams}`, {
    credentials: "include",
  });
  if (!res.ok) throw new Error("Failed to fetch overview");
  return res.json();
}

export default function ResumenPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["analytics", "overview"],
    queryFn: () => fetchOverview(),
    staleTime: 5 * 60 * 1000,
  });

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center">
        <p className="text-destructive">
          {t("common.error")}: {(error as Error).message}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Resumen</h1>
        <p className="text-muted-foreground">
          Top licitaciones, distribucion por estado y salud competitiva del mercado.
        </p>
      </div>

      {/* KPI Cards Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title={t("kpi.total_licitaciones")}
          value={isLoading ? undefined : formatNumber(data?.total_licitaciones)}
          icon={Hash}
          loading={isLoading}
        />
        <KpiCard
          title={t("kpi.importe_total")}
          value={isLoading ? undefined : formatCurrency(data?.importe_total)}
          icon={DollarSign}
          loading={isLoading}
        />
        <KpiCard
          title={t("kpi.importe_medio")}
          value={isLoading ? undefined : formatCurrency(data?.importe_medio)}
          icon={BarChart3}
          loading={isLoading}
        />
        <KpiCard
          title={t("kpi.organos_unicos")}
          value={isLoading ? undefined : formatNumber(data?.organos_unicos)}
          icon={Building2}
          trend={data?.yoy_delta}
          loading={isLoading}
        />
      </div>

      {/* Secondary KPI Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <KpiCard
          title={t("kpi.licitaciones_30d")}
          value={isLoading ? undefined : formatNumber(data?.licitaciones_30d)}
          icon={Calendar}
          loading={isLoading}
        />
        <KpiCard
          title={t("kpi.importe_30d")}
          value={isLoading ? undefined : formatCurrency(data?.importe_30d)}
          icon={DollarSign}
          loading={isLoading}
        />
        <KpiCard
          title="HHI Concentracion"
          value={isLoading ? undefined : formatNumber(data?.hhi)}
          subtitle={
            data?.hhi != null
              ? data.hhi < 1500
                ? "Mercado competitivo"
                : data.hhi < 2500
                  ? "Concentracion moderada"
                  : "Mercado concentrado"
              : undefined
          }
          icon={data?.hhi != null && data.hhi < 1500 ? TrendingDown : TrendingUp}
          loading={isLoading}
        />
      </div>

      {/* Charts Row 1: Por Estado + Por Mes */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Distribution by State */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Distribucion por Estado</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[300px] w-full" />
            ) : data?.por_estado && data.por_estado.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <PieChart>
                  <Pie
                    data={data.por_estado}
                    dataKey="n"
                    nameKey="estado"
                    cx="50%"
                    cy="50%"
                    outerRadius={100}
                    label={({ name, value }: { name?: string; value?: number }) =>
                      `${name ?? ""}: ${value ?? 0}`
                    }
                  >
                    {data.por_estado.map((_, idx) => (
                      <Cell
                        key={idx}
                        fill={CHART_COLORS[idx % CHART_COLORS.length]}
                      />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <p className="py-12 text-center text-muted-foreground">
                {t("common.no_data")}
              </p>
            )}
          </CardContent>
        </Card>

        {/* Monthly Trends */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Evolucion Mensual</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[300px] w-full" />
            ) : data?.por_mes && data.por_mes.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <AreaChart data={data.por_mes}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis
                    dataKey="mes"
                    tick={{ fontSize: 12 }}
                    className="text-muted-foreground"
                  />
                  <YAxis tick={{ fontSize: 12 }} className="text-muted-foreground" />
                  <Tooltip />
                  <Area
                    type="monotone"
                    dataKey="n_licitaciones"
                    stroke="hsl(221, 83%, 53%)"
                    fill="hsl(221, 83%, 53%)"
                    fillOpacity={0.1}
                    name="Licitaciones"
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <p className="py-12 text-center text-muted-foreground">
                {t("common.no_data")}
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Top Organos */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Top Organos Contratantes</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : data?.top_organos && data.top_organos.length > 0 ? (
            <ResponsiveContainer
              width="100%"
              height={Math.max(300, data.top_organos.length * 40)}
            >
              <BarChart
                data={data.top_organos.slice(0, 15)}
                layout="vertical"
                margin={{ left: 200 }}
              >
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis type="number" tick={{ fontSize: 12 }} />
                <YAxis
                  dataKey="organo_contratacion"
                  type="category"
                  tick={{ fontSize: 11 }}
                  width={190}
                  tickFormatter={(v: string) => truncate(v, 35)}
                />
                <Tooltip />
                <Bar
                  dataKey="n"
                  fill="hsl(221, 83%, 53%)"
                  radius={[0, 4, 4, 0]}
                  name="Licitaciones"
                />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="py-12 text-center text-muted-foreground">
              {t("common.no_data")}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Funnel Estados */}
      {data?.funnel_estados && data.funnel_estados.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Funnel de Estados</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {data.funnel_estados.map((item, idx) => {
                const maxN = Math.max(
                  ...data.funnel_estados.map((f) => f.n),
                );
                const pct = maxN > 0 ? (item.n / maxN) * 100 : 0;
                return (
                  <div key={idx} className="flex items-center gap-3">
                    <span className="w-32 text-sm text-muted-foreground truncate">
                      {item.estado}
                    </span>
                    <div className="flex-1 h-6 bg-muted rounded-sm overflow-hidden">
                      <div
                        className="h-full rounded-sm transition-all"
                        style={{
                          width: `${pct}%`,
                          backgroundColor:
                            CHART_COLORS[idx % CHART_COLORS.length],
                        }}
                      />
                    </div>
                    <Badge variant="secondary" className="tabular-nums">
                      {formatNumber(item.n)}
                    </Badge>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
