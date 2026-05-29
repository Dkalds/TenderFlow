"use client";

import * as React from "react";
import type { LucideIcon } from "lucide-react";
import { TrendingUp, TrendingDown } from "lucide-react";
import { cn } from "@/lib/utils";

export interface KpiItem {
  label: string;
  value: string;
  trend?: number;
  icon?: LucideIcon;
}

interface KpiBarProps {
  kpis: KpiItem[];
  loading?: boolean;
}

function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse rounded bg-muted-foreground/20", className)}
    />
  );
}

export function KpiBar({ kpis, loading = false }: KpiBarProps) {
  return (
    <div className="h-10 bg-muted/50 border-b flex items-center gap-4 px-4 overflow-x-auto">
      {loading
        ? Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex items-center gap-2 shrink-0">
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
                className="flex items-center gap-1.5 shrink-0 text-sm"
              >
                {Icon && (
                  <Icon className="h-3.5 w-3.5 text-muted-foreground" />
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
                    {Math.abs(kpi.trend).toFixed(1)}%
                  </span>
                )}
              </div>
            );
          })}
    </div>
  );
}
