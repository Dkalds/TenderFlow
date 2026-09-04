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
import { feedbackKeys } from "@/lib/query-keys";

/**
 * Forma de la respuesta.
 *
 * `GET /feedback/stats` no declara DTO en el backend (devuelve un `dict`), así
 * que el esquema generado no la describe y este tipo es, hasta que lo haga, la
 * suposición del frontend. Todos los campos son opcionales a propósito: la
 * pantalla ya trata la ausencia como «sin dato», no como cero.
 */
export interface FeedbackStats {
  total_labels?: number;
  pct_relevant?: number;
  last_updated?: string;
}

export function useFeedbackStats() {
  return useQuery<FeedbackStats>({
    queryKey: feedbackKeys.stats,
    queryFn: () => fetchWithAuth<FeedbackStats>("/api/v1/feedback/stats"),
    staleTime: 5 * 60_000,
  });
}
