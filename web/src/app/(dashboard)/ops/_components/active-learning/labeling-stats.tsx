"use client";

/**
 * La tira de cabecera del etiquetado: totales y cola.
 *
 * Había una tercera celda, «Relevantes», que leía un `pct_relevant` que
 * `GET /feedback/stats` no ha servido nunca: salía siempre vacía. No se calcula
 * aquí con `positivos / total` porque `relevante` no significa lo mismo en todas
 * las filas (las `human` antiguas decían «es SAP», las `revision_ti` «es TI» y
 * las del LLM mezclan las dos), y un porcentaje sobre esa mezcla no mide nada.
 */

import { StatCell, StatStrip } from "@/components/console/panel";
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
    <StatStrip columns={2}>
      <StatCell label="Etiquetas totales" value={formatNumber(stats?.total)} loading={statsLoading} />
      <StatCell label="En cola" value={formatNumber(queueSize)} loading={queueLoading} />
    </StatStrip>
  );
}
