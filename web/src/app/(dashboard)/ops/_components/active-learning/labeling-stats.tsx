"use client";

/** La tira de cabecera del etiquetado: totales, % relevantes y cola. */

import { StatCell, StatStrip } from "@/components/console/panel";
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
    <StatStrip columns={3}>
      <StatCell label="Etiquetas totales" value={formatNumber(stats?.total_labels)} loading={statsLoading} />
      <StatCell
        label="Relevantes"
        value={stats?.pct_relevant != null ? formatPercent(stats.pct_relevant) : "—"}
        loading={statsLoading}
      />
      <StatCell label="En cola" value={formatNumber(queueSize)} loading={queueLoading} />
    </StatStrip>
  );
}
