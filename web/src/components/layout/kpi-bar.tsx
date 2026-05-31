"use client";

import * as React from "react";
import type { LucideIcon } from "lucide-react";
import {
  TrendingUp,
  TrendingDown,
  FileText,
  DollarSign,
  CalendarDays,
  BarChart3,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";

export interface KpiItem {
  label: string;
  value: string;
  trend?: number;
  icon?: LucideIcon;
}

interface KpiBarProps {
  kpis?: KpiItem[];
  loading?: boolean;
}

function formatCurrency(n: number): string {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B €`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M €`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K €`;
  return `${n.toFixed(0)} €`;
}

function formatNumber(n: number): string {
  return n.toLocaleString("es-ES");
}

interface OverviewData {
  total_licitaciones: number;
  importe_total: number;
  licitaciones_30d: number;
  licitaciones_30d_trend?: number;
  yoy_delta?: number;
}

export function KpiBarConnected() {
  const { data, isLoading } = useQuery<OverviewData>({
    queryKey: ["analytics", "overview"],
    queryFn: async () => {
      const res = await fetch("/api/v1/analytics/overview", {
        credentials: "include",
      });
      if (!res.ok) throw new Error(`API error: ${res.status}`);
      return res.json();
    },
    staleTime: 60_000,
    retry: 1,
  });

  const kpis: KpiItem[] = data
    ? [
        {
          label: "Total",
          value: formatNumber(data.total_licitaciones),
          icon: FileText,
        },
        {
          label: "Importe",
          value: formatCurrency(data.importe_total),
          icon: DollarSign,
        },
        {
          label: "Últimos 30d",
          value: formatNumber(data.licitaciones_30d),
          trend: data.licitaciones_30d_trend,
          icon: CalendarDays,
        },
        {
          label: "YoY",
          value: `${(data.yoy_delta ?? 0) >= 0 ? "+" : ""}${(data.yoy_delta ?? 0).toFixed(1)}%`,
          trend: data.yoy_delta,
          icon: BarChart3,
        },
      ]
    : [];

  return <KpiBar kpis={kpis} loading={isLoading} />;
}

export function KpiBar({ kpis = [], loading = false }: KpiBarProps) {
  return (
    <div role="region" aria-label="Indicadores clave de rendimiento" className="flex min-h-11 items-center gap-3 overflow-x-auto border-b border-border/70 bg-card/80 px-4 backdrop-blur">
      {loading
        ? Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex shrink-0 items-center gap-2 rounded-md border border-border/70 bg-background/50 px-3 py-2">
              <Skeleton className="h-4 w-4 rounded" />
              <Skeleton className="h-3 w-16" />
              <Skeleton className="h-4 w-10" />
            </div>
          ))
        : kpis.map((kpi) => {
            const Icon = kpi.icon;
            return (
              <div
                key={kpi.label}
                className="flex shrink-0 items-center gap-1.5 rounded-md border border-border/70 bg-background/50 px-3 py-1.5 text-xs"
              >
                {Icon && (
                  <Icon className="h-3.5 w-3.5 text-primary" />
                )}
                <span className="text-muted-foreground">{kpi.label}:</span>
                <span className="font-medium">{kpi.value}</span>
                {kpi.trend != null && (
                  <span
                    className={cn(
                      "flex items-center gap-0.5 text-xs",
                      kpi.trend >= 0 ? "text-green-600" : "text-red-600"
                    )}
                  >
                    {kpi.trend >= 0 ? (
                      <TrendingUp className="h-3 w-3" />
                    ) : (
                      <TrendingDown className="h-3 w-3" />
                    )}
                    <span className="sr-only">{kpi.trend >= 0 ? "(subida)" : "(bajada)"}</span>
                    {Math.abs(kpi.trend).toFixed(1)}%
                  </span>
                )}
              </div>
            );
          })}
    </div>
  );
}
