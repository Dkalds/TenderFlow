"use client";

/**
 * Ficha del clasificador: el estado del etiquetado y, si ya hay un modelo
 * registrado, su versión, su métrica destacada y la deriva contra el reentreno
 * anterior. Sin modelo el panel lo dice en vez de pintar guiones.
 */

import { Fact, Panel, PanelTitle } from "@/components/console/panel";
import { cn, formatDate, formatDateTime, formatNumber, formatPercent } from "@/lib/utils";
import type { FeedbackStats } from "@/hooks/use-feedback";
import type { HeadlineMetric, ModelVersionInfo } from "../../_hooks/use-active-learning";

/** Nombre legible de cada métrica que puede destacar el hook. */
const NOMBRE_METRICA: Record<string, string> = {
  pr_auc: "PR-AUC",
  f1: "F1",
  accuracy: "Exactitud",
  precision: "Precisión",
  recall: "Exhaustividad",
};

const REJILLA = "grid gap-px overflow-hidden rounded-md border border-border/60 bg-border/60";

export function ModelInfoCard({
  stats,
  activeModel,
  metric,
  metricTrend,
  feedbacksSinceTrain,
}: {
  stats: FeedbackStats | undefined;
  activeModel: ModelVersionInfo | null;
  metric: HeadlineMetric | null;
  metricTrend: number | null;
  feedbacksSinceTrain: number;
}) {
  return (
    <Panel>
      <PanelTitle title="Modelo de clasificación" />
      <div className={cn(REJILLA, "sm:grid-cols-3")}>
        <Fact label="Total de etiquetas" value={formatNumber(stats?.total_labels)} variant="cifra" />
        <Fact
          label="Precisión estimada (% relevante)"
          value={stats?.pct_relevant != null ? formatPercent(stats.pct_relevant) : null}
          variant="cifra"
        />
        <Fact
          label="Última actualización"
          value={stats?.last_updated ? formatDateTime(stats.last_updated) : null}
        />
      </div>

      {activeModel ? (
        <div className={cn(REJILLA, "mt-3 sm:grid-cols-4")}>
          <Fact label="Modelo activo" value={`v${activeModel.version}`} variant="codigo" />
          <Fact label="Reentrenado" value={activeModel.trained_at ? formatDate(activeModel.trained_at) : null} />
          <Fact
            label={metric ? (NOMBRE_METRICA[metric.label] ?? metric.label) : "Métrica"}
            variant="cifra"
            value={
              metric ? (
                <>
                  {metric.value.toFixed(3)}
                  {metricTrend != null && metricTrend !== 0 && (
                    <span
                      className={cn(
                        "ml-1 text-tf-meta",
                        metricTrend > 0 ? "text-success" : "text-destructive",
                      )}
                    >
                      {metricTrend > 0 ? "▲" : "▼"} {Math.abs(metricTrend).toFixed(3)}
                    </span>
                  )}
                </>
              ) : null
            }
          />
          <Fact label="Etiquetas desde el reentreno" value={formatNumber(feedbacksSinceTrain)} variant="cifra" />
        </div>
      ) : (
        <p className="mt-3 text-tf-meta text-muted-foreground">
          Aún no hay un modelo registrado: etiqueta para habilitar el primer entrenamiento.
        </p>
      )}
    </Panel>
  );
}
