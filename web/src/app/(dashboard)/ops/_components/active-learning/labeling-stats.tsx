"use client";

/** Los tres KPI de cabecera del etiquetado: totales, % relevantes y cola. */

import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatNumber, formatPercent } from "@/lib/utils";
import type { FeedbackStats } from "@/hooks/use-feedback";

export function LabelingStats({
  stats,
  statsLoading,
  queueSize,
  queueLoading,
}: {
  stats: FeedbackStats | undefined;
  statsLoading: boolean;
  queueSize: number;
  queueLoading: boolean;
}) {
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <Card>
        <CardContent className="pt-6 text-center">
          {statsLoading ? (
            <Skeleton className="h-8 w-16 mx-auto" />
          ) : (
            <p className="text-2xl font-bold">
              {formatNumber(stats?.total_labels)}
            </p>
          )}
          <p className="text-sm text-muted-foreground">
            Etiquetas totales
          </p>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="pt-6 text-center">
          {statsLoading ? (
            <Skeleton className="h-8 w-16 mx-auto" />
          ) : (
            <p className="text-2xl font-bold">
              {stats?.pct_relevant != null
                ? formatPercent(stats.pct_relevant)
                : "—"}
            </p>
          )}
          <p className="text-sm text-muted-foreground">% Relevantes</p>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="pt-6 text-center">
          {queueLoading ? (
            <Skeleton className="h-8 w-16 mx-auto" />
          ) : (
            <p className="text-2xl font-bold">{formatNumber(queueSize)}</p>
          )}
          <p className="text-sm text-muted-foreground">En cola</p>
        </CardContent>
      </Card>
    </div>
  );
}
