"use client";

import * as React from "react";
import { TrendingUp, TrendingDown, AlertTriangle, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { AnimatedNumber } from "@/components/motion";

export interface KpiCardProps {
  title: string;
  value?: string;
  subtitle?: string;
  trend?: number;
  trendLabel?: string;
  icon?: LucideIcon;
  sparkline?: React.ReactNode;
  /** Show anomaly warning badge (2σ deviation detected) */
  anomaly?: boolean;
  loading?: boolean;
  className?: string;
}

export const KpiCard = React.memo(function KpiCard({
  title,
  value,
  subtitle,
  trend,
  trendLabel,
  icon: Icon,
  sparkline,
  anomaly = false,
  loading = false,
  className,
}: KpiCardProps) {
  return (
    <Card className={cn("group relative overflow-hidden hover:-translate-y-0.5 hover:border-primary/45", className)}>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="pr-8 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          {title}
        </CardTitle>
        <div className="absolute right-4 top-4 flex items-center gap-1.5">
          {anomaly && (
            <span className="grid h-6 w-6 place-items-center rounded-md bg-warning/15 text-warning" title="Anomal\u00eda detectada (desviaci\u00f3n >2\u03c3)">
              <AlertTriangle className="h-3.5 w-3.5" />
            </span>
          )}
          {Icon && (
            <span className="grid h-8 w-8 place-items-center rounded-md bg-primary/10 text-primary transition-colors group-hover:bg-primary/15">
              <Icon className="h-4 w-4" />
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-8 w-24" />
        ) : (
          <AnimatedNumber
            value={value ?? "-"}
            className="tf-tnum block text-[1.75rem] font-bold leading-none text-foreground"
          />
        )}

        {!loading && (subtitle || trend != null) && (
          <div className="mt-1.5 flex items-center gap-2 text-xs">
            {trend != null && (
              <span
                className={cn(
                  "inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 font-semibold tabular-nums",
                  trend >= 0
                    ? "bg-success/12 text-success"
                    : "bg-destructive/12 text-destructive"
                )}
              >
                {trend >= 0 ? (
                  <TrendingUp className="h-3 w-3" />
                ) : (
                  <TrendingDown className="h-3 w-3" />
                )}
                {trend >= 0 ? "+" : ""}
                {trend.toFixed(1)}%
              </span>
            )}
            {trendLabel && (
              <span className="text-muted-foreground">{trendLabel}</span>
            )}
            {subtitle && !trendLabel && (
              <span className="text-muted-foreground">{subtitle}</span>
            )}
          </div>
        )}

        {/* Sparkline placeholder — pass a recharts AreaChart as children */}
        {sparkline && (
          <div className="mt-3 h-12 w-full">{sparkline}</div>
        )}
      </CardContent>
    </Card>
  );
});
