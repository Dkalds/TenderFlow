"use client";

/**
 * Los KPI de cabecera del etiquetado: totales y cola.
 *
 * Había un tercero, «% Relevantes», que leía un `pct_relevant` que
 * `GET /feedback/stats` no ha servido nunca: salía siempre vacío. No se calcula
 * aquí con `positivos / total` porque `relevante` no significa lo mismo en todas
 * las filas (las `human` antiguas decían «es SAP», las `revision_ti` «es TI» y
 * las del LLM mezclan las dos), y un porcentaje sobre esa mezcla no mide nada.
 */

import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatNumber } from "@/lib/utils";
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
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <CardContent className="pt-6 text-center">
          {statsLoading ? (
            <Skeleton className="h-8 w-16 mx-auto" />
          ) : (
            <p className="text-2xl font-bold">
              {formatNumber(stats?.total)}
            </p>
          )}
          <p className="text-sm text-muted-foreground">
            Etiquetas totales
          </p>
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
