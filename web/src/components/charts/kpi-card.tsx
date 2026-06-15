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

/** Vertical accent stripe color, keyed to the design-system score bands. */
type KpiAccent = "primary" | "hot" | "warm" | "cold" | "skip";

const ACCENT_BG: Record<KpiAccent, string> = {
  primary: "bg-primary",
  hot: "bg-[hsl(var(--score-hot))]",
  warm: "bg-[hsl(var(--score-warm))]",
  cold: "bg-[hsl(var(--score-cold))]",
  skip: "bg-[hsl(var(--score-skip))]",
};

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
  /** Left accent stripe color, keyed to score bands. */
  accent?: KpiAccent;
  /** Optional target/threshold shown next to the trend (e.g. "meta 1.000"). */
  target?: string;
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
  accent,
  target,
  loading = false,
  className,
}: KpiCardProps) {
  return (
    <Card className={cn("group relative overflow-hidden transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/45 hover:shadow-lg", className)}>
      {accent && (
        <span
          aria-hidden="true"
          className={cn("absolute inset-y-0 left-0 w-1", ACCENT_BG[accent])}
        />
      )}
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

        {!loading && (subtitle || trend != null || target) && (
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
            {target && (
              <span className="text-muted-foreground/80 tabular-nums">meta {target}</span>
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
