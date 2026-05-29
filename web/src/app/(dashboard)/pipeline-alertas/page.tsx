"use client";

import { useQuery } from "@tanstack/react-query";
import { KpiCard } from "@/components/charts/kpi-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { formatCurrency, formatNumber, formatDate, truncate } from "@/lib/utils";
import {
  Bell,
  Clock,
  AlertTriangle,
  CalendarClock,
  Target,
  Building2,
} from "lucide-react";

interface PipelineItem {
  id?: string;
  titulo: string;
  organo?: string;
  importe?: number;
  fecha_limite?: string;
  dias_restantes?: number;
  estado?: string;
  score?: number;
}

interface PipelineData {
  total_en_plazo: number;
  vencen_7d: number;
  vencen_30d: number;
  score_promedio: number;
  items: PipelineItem[];
}

async function fetchPipeline(): Promise<PipelineData> {
  const res = await fetch("/api/v1/analytics/pipeline", {
    credentials: "include",
  });
  if (!res.ok) throw new Error("Error al cargar datos de pipeline");
  return res.json();
}

function getDiasColor(dias: number | undefined): string {
  if (dias == null) return "text-muted-foreground";
  if (dias < 7) return "text-red-600 dark:text-red-400";
  if (dias < 30) return "text-yellow-600 dark:text-yellow-400";
  return "text-green-600 dark:text-green-400";
}

function getDiasBadgeVariant(dias: number | undefined): "destructive" | "secondary" | "outline" {
  if (dias == null) return "secondary";
  if (dias < 7) return "destructive";
  if (dias < 30) return "secondary";
  return "outline";
}

export default function PipelineAlertasPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["analytics", "pipeline"],
    queryFn: fetchPipeline,
    staleTime: 2 * 60 * 1000,
  });

  // Sort by most urgent first
  const sortedItems = data?.items
    ? [...data.items].sort((a, b) => (a.dias_restantes ?? 999) - (b.dias_restantes ?? 999))
    : [];

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center">
        <p className="text-destructive">Error: {(error as Error).message}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Pipeline &amp; Alertas</h1>
        <p className="text-muted-foreground">
          Alertas de plazos y seguimiento de licitaciones activas.
        </p>
      </div>

      {/* KPI Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Total en Plazo"
          value={isLoading ? undefined : formatNumber(data?.total_en_plazo)}
          icon={Clock}
          loading={isLoading}
        />
        <KpiCard
          title="Vencen en 7 dias"
          value={isLoading ? undefined : formatNumber(data?.vencen_7d)}
          icon={AlertTriangle}
          loading={isLoading}
          className={
            data?.vencen_7d && data.vencen_7d > 0
              ? "border-red-200 dark:border-red-900"
              : undefined
          }
        />
        <KpiCard
          title="Vencen en 30 dias"
          value={isLoading ? undefined : formatNumber(data?.vencen_30d)}
          icon={CalendarClock}
          loading={isLoading}
          className={
            data?.vencen_30d && data.vencen_30d > 0
              ? "border-yellow-200 dark:border-yellow-900"
              : undefined
          }
        />
        <KpiCard
          title="Score Promedio"
          value={isLoading ? undefined : data?.score_promedio != null ? data.score_promedio.toFixed(1) : "-"}
          icon={Target}
          loading={isLoading}
        />
      </div>

      {/* Timeline / List */}
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
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-24 w-full" />
              ))}
            </div>
          ) : sortedItems.length > 0 ? (
            <div className="space-y-3">
              {sortedItems.map((item, idx) => (
                <div
                  key={item.id ?? idx}
                  className="rounded-lg border p-4 hover:bg-muted/50 transition-colors"
                >
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    <div className="flex-1 min-w-0">
                      <h4 className="text-sm font-medium leading-snug">
                        {truncate(item.titulo, 100)}
                      </h4>
                      {item.organo && (
                        <div className="flex items-center gap-1.5 mt-1 text-xs text-muted-foreground">
                          <Building2 className="h-3 w-3 shrink-0" />
                          {truncate(item.organo, 60)}
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
    </div>
  );
}
