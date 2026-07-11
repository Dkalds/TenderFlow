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
  SlidersHorizontal,
} from "lucide-react";
import { usePathname } from "next/navigation";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useScrolledPast } from "@/hooks/use-scrolled-past";
import { useFilterParams } from "@/lib/filters";
import { pathUsesGlobalFilters } from "@/lib/navigation";
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
  /** Muestra el badge "Filtrado" cuando los KPI respetan filtros activos. */
  filtered?: boolean;
  /** Colapsa visualmente la barra (scroll hacia abajo) sin desmontarla. */
  collapsed?: boolean;
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
  const pathname = usePathname();
  const filtersApply = pathUsesGlobalFilters(pathname);
  const filterParams = useFilterParams();
  // Los KPI respetan los filtros globales activos (mismo dataset que los
  // charts de la página); antes mostraban totales globales encima de vistas
  // filtradas.
  const { data, isLoading } = useFilteredQuery<OverviewData>(
    ["analytics", "overview"],
    "/api/v1/analytics/overview",
    { staleTime: 60_000, retry: 1, enabled: filtersApply },
  );
  // Colapso adicional al hacer scroll (no reemplaza el ocultado por
  // `!filtersApply`, que tiene prioridad y desmonta el componente entero).
  const scrolled = useScrolledPast(8);

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

  if (!filtersApply) return null;

  return (
    <KpiBar
      kpis={kpis}
      loading={isLoading}
      filtered={Object.keys(filterParams).length > 0}
      collapsed={scrolled}
    />
  );
}

export function KpiBar({ kpis = [], loading = false, filtered = false, collapsed = false }: KpiBarProps) {
  return (
    <div
      role="region"
      aria-label="Indicadores clave de rendimiento"
      className={cn(
        "flex items-center gap-3 overflow-x-auto border-b border-border/70 bg-card/80 px-4 backdrop-blur transition-all duration-200",
        collapsed ? "max-h-0 min-h-0 opacity-0 overflow-hidden py-0 border-b-0" : "max-h-20 min-h-11 opacity-100",
      )}
    >
      {filtered && (
        <span className="flex shrink-0 items-center gap-1 rounded-full border border-primary/20 bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
          <SlidersHorizontal className="h-3 w-3" />
          Filtrado
        </span>
      )}
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
                <span className="tf-tnum font-medium">{kpi.value}</span>
                {kpi.trend != null && (
                  <span
                    className={cn(
                      "flex items-center gap-0.5 text-xs font-medium tabular-nums",
                      kpi.trend >= 0 ? "text-success" : "text-destructive"
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
