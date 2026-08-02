"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { useDataFreshness } from "@/hooks/use-data-freshness";
import { useSourceFreshness } from "@/hooks/use-source-freshness";
import { StatCell, StatStrip } from "@/components/console/panel";
import { formatNumber } from "@/lib/utils";

/**
 * Tira de salud común a las cinco vistas de Ops.
 *
 * Antes había que entrar en dos pantallas distintas para saber si el DLQ tenía
 * cola: la observabilidad vivía en una, la calidad del dato en otra y la de
 * etiquetado en una tercera. El turno de guardia empieza por las mismas cuatro
 * preguntas, así que van arriba y no cambian al cambiar de vista.
 *
 * Los cuatro números son los que las APIs devuelven de verdad. En particular
 * «Etiquetas registradas» cuenta lo etiquetado, no lo pendiente: la cola no
 * expone un total y un pendiente inventado sería peor que ninguno.
 */

interface QualityMetrics {
  dlq_count?: number;
}

interface FeedbackStats {
  total_labels?: number;
}

export function OpsHealthStrip() {
  const sources = useSourceFreshness();
  const { relative } = useDataFreshness();

  const quality = useQuery<QualityMetrics>({
    queryKey: ["analytics", "quality"],
    queryFn: () => fetchWithAuth<QualityMetrics>("/api/v1/analytics/quality"),
    staleTime: 60_000,
  });

  const feedback = useQuery<FeedbackStats>({
    queryKey: ["feedback-stats"],
    queryFn: () => fetchWithAuth<FeedbackStats>("/api/v1/feedback/stats"),
    staleTime: 5 * 60_000,
  });

  const healthy = sources.data?.healthy_sources;
  const total = sources.data?.total_sources;
  const sourcesDegraded = healthy != null && total != null && healthy < total;
  const dlq = quality.data?.dlq_count ?? 0;

  return (
    <StatStrip className="mb-4">
      <StatCell
        label="Fuentes al día"
        value={healthy != null && total != null ? `${healthy} de ${total}` : "—"}
        hint={sourcesDegraded ? "alguna fuente degradada" : "todas responden"}
        accent={sourcesDegraded ? "hsl(var(--warning))" : undefined}
        loading={sources.isLoading}
      />
      <StatCell
        label="Frescura del dato"
        value={relative ?? "—"}
        hint="último sellado de dato"
        loading={!relative && sources.isLoading}
      />
      <StatCell
        label="Cola DLQ"
        value={formatNumber(dlq)}
        hint={dlq > 0 ? "hay mensajes sin procesar" : "vacía"}
        accent={dlq > 0 ? "hsl(var(--destructive))" : undefined}
        loading={quality.isLoading}
      />
      <StatCell
        label="Etiquetas registradas"
        value={formatNumber(feedback.data?.total_labels ?? 0)}
        hint="acumulado de active learning"
        loading={feedback.isLoading}
      />
    </StatStrip>
  );
}
