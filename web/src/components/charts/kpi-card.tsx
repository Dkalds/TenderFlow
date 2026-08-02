"use client";

import * as React from "react";
import Link from "next/link";
import { TrendingUp, TrendingDown, AlertTriangle, ArrowUpRight, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";

/** Vertical accent stripe color, keyed to the design-system score bands. */
type KpiAccent = "primary" | "hot" | "warm" | "cold" | "skip";

// A JS string constant (not raw JSX text) so it can't regress into literal
// `\uXXXX` escape sequences — JSX text/attribute strings are not run through
// the JS escape parser, unlike a real string literal referenced via `{}`.
const ANOMALY_LABEL = "Anomalía detectada (desviación >2σ)";

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
  /**
   * Optional drill-down destination. When set, the whole card becomes an
   * accessible link (keyboard-focusable, with a hover affordance) that
   * navigates to the filtered listing backing the metric.
   */
  href?: string;
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
  href,
  loading = false,
  className,
}: KpiCardProps) {
  const card = (
    <Card
      className={cn(
        // El diseño no apila tarjetas con sombra: son celdas planas y
        // compactas de una tira de dato. Alto mínimo de 84px en vez de 124, sin
        // elevación y sin desplazamiento al hover — un KPI no es un botón.
        "group relative h-full min-h-[5.25rem] overflow-hidden border-border/60 bg-card/70 shadow-none transition-colors duration-140 hover:border-primary/45",
        href && "cursor-pointer",
        className,
      )}
    >
      {accent && (
        <span
          aria-hidden="true"
          className={cn("absolute inset-y-0 left-0 w-1", ACCENT_BG[accent])}
        />
      )}
      <CardHeader className="flex flex-row items-center justify-between px-3.5 pb-1.5 pt-3">
        <CardTitle className="pr-8 font-mono text-[8.5px] font-semibold uppercase tracking-[0.11em] text-muted-foreground">
          {title}
        </CardTitle>
        <div className="absolute right-3 top-2.5 flex items-center gap-1.5">
          {anomaly && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="grid h-6 w-6 place-items-center rounded-md bg-warning/15 text-warning">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  <span className="sr-only">{ANOMALY_LABEL}</span>
                </span>
              </TooltipTrigger>
              <TooltipContent>{ANOMALY_LABEL}</TooltipContent>
            </Tooltip>
          )}
          {Icon && (
            <span className="grid h-6 w-6 place-items-center rounded-md bg-primary/10 text-primary transition-colors group-hover:bg-primary/15">
              <Icon className="h-3.5 w-3.5" />
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent className="px-3.5 pb-3">
        {loading ? (
          <Skeleton className="h-6 w-24 rounded" />
        ) : (
          // Static render, no count-up: this is the number the user came to
          // read, and it re-triggers on every filter change — animating it
          // fails the frequency gate (find-animation-opportunities) and the
          // previous count-up re-rendered on every animation frame.
          <span className="tf-tnum block font-mono text-[22px] font-semibold leading-none text-foreground">
            {value ?? "—"}
          </span>
        )}

        {!loading && (subtitle || trend != null || target) && (
          <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10.5px]">
            {trend != null && (
              <span
                className={cn(
                  "inline-flex items-center gap-0.5 rounded px-1 py-0.5 font-mono font-semibold tabular-nums",
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
      {href && (
        <ArrowUpRight
          aria-hidden="true"
          className="absolute bottom-3 right-3 h-4 w-4 text-muted-foreground/50 transition-colors group-hover:text-primary"
        />
      )}
    </Card>
  );

  if (href) {
    return (
      <Link
        href={href}
        aria-label={`${title}: ver detalle`}
        className="block h-full rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        {card}
      </Link>
    );
  }

  return card;
});
