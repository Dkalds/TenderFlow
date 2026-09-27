"use client";

/**
 * Ficha del clasificador: el estado del etiquetado y, si ya hay un modelo
 * registrado, su versión, su métrica destacada y la deriva contra el reentreno
 * anterior. Sin modelo la tarjeta lo dice en vez de pintar guiones.
 *
 * Sin «precisión estimada (% relevante)»: leía un `pct_relevant` que la API no
 * sirve (ver `labeling-stats.tsx`, que explica por qué tampoco se calcula aquí).
 */

import { Activity } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { cn, formatDate, formatDateTime, formatNumber } from "@/lib/utils";
import type { FeedbackStats } from "@/hooks/use-feedback";
import type { HeadlineMetric, ModelVersionInfo } from "../../_lib/active-learning";

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
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Activity className="h-4 w-4" />
          Modelo de clasificación
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 sm:grid-cols-2 text-sm">
          <div>
            <p className="text-muted-foreground">Total etiquetas</p>
            <p className="font-medium">
              {formatNumber(stats?.total)}
            </p>
          </div>
          <div>
            <p className="text-muted-foreground">Última actualización</p>
            <p className="font-medium">
              {stats?.last_feedback_at
                ? formatDateTime(stats.last_feedback_at)
                : "—"}
            </p>
          </div>
        </div>

        {activeModel ? (
          <>
            <Separator className="my-4" />
            <div className="grid gap-4 sm:grid-cols-4 text-sm">
              <div>
                <p className="text-muted-foreground">Modelo activo</p>
                <p className="font-medium tabular-nums">v{activeModel.version}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Reentrenado</p>
                <p className="font-medium">
                  {activeModel.trained_at
                    ? formatDate(activeModel.trained_at)
                    : "—"}
                </p>
              </div>
              <div>
                <p className="text-muted-foreground">
                  {metric ? metric.label.toUpperCase() : "Métrica"}
                </p>
                <p className="font-medium tabular-nums">
                  {metric ? metric.value.toFixed(3) : "—"}
                  {metricTrend != null && metricTrend !== 0 && (
                    <span
                      className={cn(
                        "ml-1 text-xs",
                        metricTrend > 0 ? "text-green-600" : "text-red-600",
                      )}
                    >
                      {metricTrend > 0 ? "▲" : "▼"} {Math.abs(metricTrend).toFixed(3)}
                    </span>
                  )}
                </p>
              </div>
              <div>
                <p className="text-muted-foreground">Etiquetas desde el reentreno</p>
                <p className="font-medium tabular-nums">
                  {formatNumber(feedbacksSinceTrain)}
                </p>
              </div>
            </div>
          </>
        ) : (
          <p className="mt-3 text-xs text-muted-foreground">
            Aun no hay un modelo registrado; etiqueta para habilitar el primer
            entrenamiento.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
