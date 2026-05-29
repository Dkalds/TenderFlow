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
import { ShieldCheck, AlertTriangle, Clock, Database } from "lucide-react";
import { formatNumber, formatPercent } from "@/lib/utils";
import { cn } from "@/lib/utils";

interface QualityData {
  total_records?: number;
  pct_cpv?: number;
  pct_importe?: number;
  pct_fecha?: number;
  pct_titulo?: number;
  dlq_count?: number;
  last_scrape_at?: string;
  [key: string]: unknown;
}

function completenessColor(pct: number): string {
  if (pct > 80) return "bg-green-500";
  if (pct >= 50) return "bg-yellow-500";
  return "bg-red-500";
}

function completenessTextColor(pct: number): string {
  if (pct > 80) return "text-green-700";
  if (pct >= 50) return "text-yellow-700";
  return "text-red-700";
}

function ProgressBar({ label, pct, loading }: { label: string; pct?: number; loading: boolean }) {
  if (loading) {
    return (
      <div className="space-y-1">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-4 w-full" />
      </div>
    );
  }
  const value = pct ?? 0;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{label}</span>
        <span className={cn("text-sm font-semibold", completenessTextColor(value))}>
          {formatPercent(value)}
        </span>
      </div>
      <div className="h-3 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all", completenessColor(value))}
          style={{ width: `${Math.min(value, 100)}%` }}
        />
      </div>
    </div>
  );
}

export default function CalidadDatosPage() {
  const { data, isLoading, isError } = useQuery<QualityData>({
    queryKey: ["analytics-quality"],
    queryFn: async () => {
      const res = await fetch("/api/v1/analytics/quality", { credentials: "include" });
      if (!res.ok) throw new Error(`Error ${res.status}`);
      return res.json();
    },
  });

  const lastScrape = data?.last_scrape_at ? new Date(data.last_scrape_at) : null;
  const hoursAgo = lastScrape
    ? Math.round((Date.now() - lastScrape.getTime()) / 3_600_000)
    : null;
  const scrapeStale = hoursAgo != null && hoursAgo > 24;

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
      <div className="grid gap-4 md:grid-cols-4">
        <KpiCard
          title="Total registros"
          value={data?.total_records != null ? formatNumber(data.total_records) : undefined}
          icon={Database}
          loading={isLoading}
        />
        <KpiCard
          title="Completitud CPV"
          value={data?.pct_cpv != null ? formatPercent(data.pct_cpv) : undefined}
          icon={ShieldCheck}
          loading={isLoading}
        />
        <KpiCard
          title="Completitud Importe"
          value={data?.pct_importe != null ? formatPercent(data.pct_importe) : undefined}
          icon={ShieldCheck}
          loading={isLoading}
        />
        <KpiCard
          title="Ultima ingesta"
          value={
            isLoading
              ? undefined
              : hoursAgo != null
                ? `Hace ${hoursAgo}h`
                : "N/A"
          }
          subtitle={scrapeStale ? "Datos potencialmente desactualizados" : undefined}
          icon={Clock}
          loading={isLoading}
        />
      </div>

      <Separator />

      {/* Completeness bars */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5" />
            Metricas de completitud
          </CardTitle>
          <CardDescription>
            Porcentaje de registros con campos completos
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <ProgressBar label="Titulo" pct={data?.pct_titulo} loading={isLoading} />
          <ProgressBar label="CPV" pct={data?.pct_cpv} loading={isLoading} />
          <ProgressBar label="Importe" pct={data?.pct_importe} loading={isLoading} />
          <ProgressBar label="Fecha" pct={data?.pct_fecha} loading={isLoading} />
        </CardContent>
      </Card>

      {/* DLQ + Scrape freshness */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card className={data?.dlq_count && data.dlq_count > 0 ? "border-yellow-500" : ""}>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="h-4 w-4" />
              Dead Letter Queue (DLQ)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <>
                <p className="text-2xl font-bold">{data?.dlq_count ?? 0}</p>
                <p className="text-sm text-muted-foreground">
                  registros en cola de errores
                </p>
                {data?.dlq_count != null && data.dlq_count > 0 && (
                  <Badge variant="destructive" className="mt-2">
                    Requiere atencion
                  </Badge>
                )}
              </>
            )}
          </CardContent>
        </Card>

        <Card className={scrapeStale ? "border-yellow-500" : ""}>
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
                {scrapeStale && (
                  <Badge variant="destructive" className="mt-2">
                    Mas de 24h sin actualizar
                  </Badge>
                )}
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
