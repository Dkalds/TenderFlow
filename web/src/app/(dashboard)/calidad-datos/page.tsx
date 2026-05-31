"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { KpiCard } from "@/components/charts/kpi-card";
import {
  ShieldCheck,
  AlertTriangle,
  Clock,
  Database,
  Users,
  Boxes,
} from "lucide-react";
import { formatNumber, formatPercent, cn } from "@/lib/utils";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

interface ColumnCompleteness {
  columna: string;
  pct: number;
}

interface QualityData {
  total_records?: number;
  pct_cpv?: number;
  pct_importe?: number;
  pct_fecha?: number;
  pct_titulo?: number;
  completitud_columnas?: ColumnCompleteness[];
  cobertura_nif?: number;
  cobertura_modulo_sap?: number;
  dlq_count?: number;
  last_scrape_hours_ago?: number;
  last_scrape_at?: string;
  [key: string]: unknown;
}

function barColor(pct: number): string {
  if (pct >= 90) return "#22c55e"; // green-500
  if (pct >= 70) return "#eab308"; // yellow-500
  return "#ef4444"; // red-500
}

function freshnessInfo(hours: number | null | undefined): {
  label: string;
  color: string;
  badge: "default" | "secondary" | "destructive";
} {
  if (hours == null) return { label: "N/A", color: "", badge: "secondary" };
  if (hours < 6)
    return { label: "Actualizado", color: "text-green-700", badge: "default" };
  if (hours <= 24)
    return { label: "Pendiente", color: "text-yellow-700", badge: "secondary" };
  return { label: "Obsoleto", color: "text-red-700", badge: "destructive" };
}

export default function CalidadDatosPage() {
  const { data, isLoading, isError } = useQuery<QualityData>({
    queryKey: ["analytics-quality"],
    queryFn: async () => {
      const res = await fetch("/api/v1/analytics/quality", {
        credentials: "include",
      });
      if (res.status === 401) throw new Error("Sesion expirada");
      if (!res.ok) throw new Error(`Error ${res.status}`);
      return res.json();
    },
  });

  const hoursAgo = data?.last_scrape_hours_ago ?? null;
  const freshness = freshnessInfo(hoursAgo);

  // Build chart data: prefer completitud_columnas, fallback to pct_* fields
  const chartData: ColumnCompleteness[] =
    data?.completitud_columnas && data.completitud_columnas.length > 0
      ? data.completitud_columnas
      : [
          { columna: "Titulo", pct: data?.pct_titulo ?? 0 },
          { columna: "CPV", pct: data?.pct_cpv ?? 0 },
          { columna: "Importe", pct: data?.pct_importe ?? 0 },
          { columna: "Fecha", pct: data?.pct_fecha ?? 0 },
        ];

  const dlqCount = data?.dlq_count ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Calidad de Datos</h1>
        <p className="text-muted-foreground">
          Completitud y consistencia del dataset.
        </p>
      </div>

      {isError && (
        <Card className="border-destructive">
          <CardContent className="pt-6 text-destructive">
            Error al cargar metricas de calidad. Verifica que la API este activa.
          </CardContent>
        </Card>
      )}

      {/* KPI row */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Total registros"
          value={
            data?.total_records != null
              ? formatNumber(data.total_records)
              : undefined
          }
          icon={Database}
          loading={isLoading}
        />
        <KpiCard
          title="Cobertura NIF"
          value={
            data?.cobertura_nif != null
              ? formatPercent(data.cobertura_nif)
              : undefined
          }
          icon={Users}
          loading={isLoading}
        />
        <KpiCard
          title="Cobertura Modulo SAP"
          value={
            data?.cobertura_modulo_sap != null
              ? formatPercent(data.cobertura_modulo_sap)
              : undefined
          }
          icon={Boxes}
          loading={isLoading}
        />
        <KpiCard
          title="Frescura scraping"
          value={
            isLoading
              ? undefined
              : hoursAgo != null
                ? `${hoursAgo}h`
                : "N/A"
          }
          subtitle={freshness.label}
          icon={Clock}
          loading={isLoading}
          className={cn(
            !isLoading &&
              hoursAgo != null &&
              hoursAgo > 24 &&
              "border-red-200 dark:border-red-800",
            !isLoading &&
              hoursAgo != null &&
              hoursAgo > 6 &&
              hoursAgo <= 24 &&
              "border-yellow-200 dark:border-yellow-800",
          )}
        />
      </div>

      <Separator />

      {/* Completeness horizontal bar chart */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5" />
            Completitud por columna
          </CardTitle>
          <CardDescription>
            Porcentaje de registros con campos completos
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {[1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-6 w-full" />
              ))}
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(chartData.length * 40, 200)}>
              <BarChart
                data={chartData}
                layout="vertical"
                margin={{ top: 5, right: 30, left: 80, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" domain={[0, 100]} unit="%" />
                <YAxis
                  type="category"
                  dataKey="columna"
                  width={75}
                  tick={{ fontSize: 12 }}
                />
                <Tooltip
                  formatter={(value) => [`${Number(value).toFixed(1)}%`, "Completitud"]}
                />
                <Bar dataKey="pct" radius={[0, 4, 4, 0]} barSize={20}>
                  {chartData.map((entry, idx) => (
                    <Cell key={idx} fill={barColor(entry.pct)} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      {/* DLQ + Scrape freshness */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card
          className={cn(
            dlqCount > 0 &&
              "border-red-500 bg-red-50/50 dark:bg-red-950/20",
          )}
        >
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle
                className={cn(
                  "h-4 w-4",
                  dlqCount > 0 ? "text-red-600" : "text-muted-foreground",
                )}
              />
              Dead Letter Queue (DLQ)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <>
                <p
                  className={cn(
                    "text-2xl font-bold",
                    dlqCount > 0 && "text-red-600",
                  )}
                >
                  {dlqCount}
                </p>
                <p className="text-sm text-muted-foreground">
                  registros en cola de errores
                </p>
                {dlqCount > 0 && (
                  <Badge variant="destructive" className="mt-2">
                    Requiere atencion
                  </Badge>
                )}
              </>
            )}
          </CardContent>
        </Card>

        <Card
          className={cn(
            hoursAgo != null &&
              hoursAgo > 24 &&
              "border-red-500",
            hoursAgo != null &&
              hoursAgo > 6 &&
              hoursAgo! <= 24 &&
              "border-yellow-500",
          )}
        >
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Clock className="h-4 w-4" />
              Frescura del scraping
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-8 w-24" />
            ) : (
              <>
                <p className="text-2xl font-bold">
                  {hoursAgo != null ? `${hoursAgo} horas` : "N/A"}
                </p>
                <p className="text-sm text-muted-foreground">
                  desde la ultima ingesta
                </p>
                <Badge variant={freshness.badge} className="mt-2">
                  {freshness.label}
                </Badge>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Weekly pipeline summary */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Database className="h-4 w-4" />
            Resumen del pipeline
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-8 w-32" />
          ) : (
            <div className="flex items-center gap-4">
              <div>
                <p className="text-2xl font-bold">
                  {formatNumber(data?.total_records)}
                </p>
                <p className="text-sm text-muted-foreground">
                  registros totales en el sistema
                </p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
