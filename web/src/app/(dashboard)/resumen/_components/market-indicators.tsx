"use client";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatPercent, formatNumber } from "@/lib/utils";
import { Users, BarChart3, TrendingDown, Timer, Lock } from "lucide-react";
import type { ExtendedOverview } from "./types";

interface MarketIndicatorsProps {
  data: ExtendedOverview | undefined;
  isLoading: boolean;
}

export function MarketIndicators({ data, isLoading }: MarketIndicatorsProps) {
  const hhiColor = (v: number | null | undefined) => {
    if (v == null) return "text-muted-foreground";
    if (v < 1500) return "text-green-600";
    if (v < 2500) return "text-yellow-600";
    return "text-red-600";
  };

  const marketMetrics = [
    {
      label: "% PYMEs adjudicadas",
      value: data?.pct_pyme != null ? formatPercent(data.pct_pyme) : "-",
      color:
        data?.pct_pyme != null && data.pct_pyme >= 40
          ? "text-green-600"
          : data?.pct_pyme != null && data.pct_pyme < 20
            ? "text-red-600"
            : "text-foreground",
      icon: Users,
    },
    {
      label: "Concentracion top 10",
      value: data?.concentracion_top10 != null ? formatPercent(data.concentracion_top10) : "-",
      color:
        data?.concentracion_top10 != null && data.concentracion_top10 < 60
          ? "text-green-600"
          : data?.concentracion_top10 != null && data.concentracion_top10 >= 80
            ? "text-red-600"
            : "text-foreground",
      icon: BarChart3,
    },
    {
      label: "Tasa anulacion",
      value: data?.tasa_anulacion != null ? formatPercent(data.tasa_anulacion) : "-",
      color:
        data?.tasa_anulacion != null && data.tasa_anulacion > 10
          ? "text-red-600"
          : "text-foreground",
      icon: TrendingDown,
    },
  ] as const;

  const competitiveMetrics = [
    {
      label: "Lead time pub→adj",
      value: data?.lead_time_medio != null ? `${formatNumber(data.lead_time_medio)} dias` : "N/A",
      color: "text-foreground" as const,
      icon: Timer,
      subtitle: undefined as string | undefined,
    },
    {
      label: "HHI Concentracion",
      value: data?.hhi != null ? formatNumber(data.hhi) : "-",
      color: hhiColor(data?.hhi),
      icon: BarChart3,
      subtitle:
        data?.hhi != null
          ? data.hhi < 1500
            ? "Competitivo"
            : data.hhi < 2500
              ? "Moderado"
              : "Concentrado"
          : undefined,
    },
    {
      label: "% Oferta unica",
      value: data?.pct_oferta_unica != null ? formatPercent(data.pct_oferta_unica) : "-",
      color:
        data?.pct_oferta_unica != null && data.pct_oferta_unica < 20
          ? "text-green-600"
          : data?.pct_oferta_unica != null && data.pct_oferta_unica >= 40
            ? "text-red-600"
            : "text-foreground",
      icon: Lock,
      subtitle: undefined as string | undefined,
    },
  ];

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
        Indicadores de Mercado
      </h3>
      <div className="grid gap-3 grid-cols-2 md:grid-cols-3">
        {marketMetrics.map((metric) => (
          <Card key={metric.label} className="p-3">
            <div className="flex items-center gap-2 mb-1">
              <metric.icon className="h-3.5 w-3.5 text-muted-foreground" />
              <p className="text-xs text-muted-foreground">{metric.label}</p>
            </div>
            <div className={cn("text-lg font-semibold", isLoading ? "" : metric.color)}>
              {isLoading ? <Skeleton className="h-6 w-16" /> : metric.value}
            </div>
          </Card>
        ))}
      </div>

      <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider pt-2">
        Salud Competitiva
      </h3>
      <div className="grid gap-3 grid-cols-2 md:grid-cols-3">
        {competitiveMetrics.map((metric) => (
          <Card key={metric.label} className="p-3">
            <div className="flex items-center gap-2 mb-1">
              <metric.icon className="h-3.5 w-3.5 text-muted-foreground" />
              <p className="text-xs text-muted-foreground">{metric.label}</p>
            </div>
            <div className={cn("text-lg font-semibold", isLoading ? "" : metric.color)}>
              {isLoading ? <Skeleton className="h-6 w-16" /> : metric.value}
            </div>
            {metric.subtitle && !isLoading && (
              <p className="text-[10px] text-muted-foreground mt-0.5">{metric.subtitle}</p>
            )}
          </Card>
        ))}
      </div>
    </div>
  );
}
