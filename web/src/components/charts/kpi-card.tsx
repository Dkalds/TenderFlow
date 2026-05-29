"use client";

import * as React from "react";
import { TrendingUp, TrendingDown, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export interface KpiCardProps {
  title: string;
  value?: string;
  subtitle?: string;
  trend?: number;
  trendLabel?: string;
  icon?: LucideIcon;
  sparkline?: React.ReactNode;
  loading?: boolean;
  className?: string;
}

export function KpiCard({
  title,
  value,
  subtitle,
  trend,
  trendLabel,
  icon: Icon,
  sparkline,
  loading = false,
  className,
}: KpiCardProps) {
  return (
    <Card className={cn("relative overflow-hidden", className)}>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
        {Icon && <Icon className="h-4 w-4 text-muted-foreground" />}
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-8 w-24" />
        ) : (
          <div className="text-2xl font-bold">{value ?? "-"}</div>
        )}

        {!loading && (subtitle || trend != null) && (
          <div className="mt-1 flex items-center gap-2 text-xs">
            {trend != null && (
              <span
                className={cn(
                  "flex items-center gap-0.5 font-medium",
                  trend >= 0 ? "text-green-600" : "text-red-600"
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
}
