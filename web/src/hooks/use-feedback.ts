/**
 * Estadísticas de etiquetado (`GET /feedback/stats`).
 *
 * La consulta estaba copiada en `ops/_components/health-strip.tsx` y en
 * `ops/_components/active-learning-view.tsx`, cada una con su propia interfaz
 * local de la respuesta y bajo la misma clave `["feedback-stats"]`. Las dos
 * vistas se montan a la vez en `/ops`, así que compartían caché sin compartir
 * ni el tipo ni el `staleTime`.
 */
"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { feedbackKeys } from "@/lib/query-keys";

/**
 * Forma de la respuesta: el DTO `FeedbackStats` del backend, del esquema
 * generado. Hasta 2026-09-28 era una interfaz escrita a mano con
 * `total_labels`, `pct_relevant` y `last_updated`, campos que la API no ha
 * servido nunca (manda `total`, `positivos`, `negativos` y
 * `last_feedback_at`): «Etiquetas totales» y «Última actualización» salían
 * vacías en `/ops` sin que nada fallara.
 */
export type FeedbackStats = Schemas["FeedbackStats"];

export function useFeedbackStats() {
  return useQuery<FeedbackStats>({
    queryKey: feedbackKeys.stats,
    queryFn: () => fetchWithAuth<FeedbackStats>("/api/v1/feedback/stats"),
    staleTime: 5 * 60_000,
  });
}
