"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api-client";
import { formatRelativeTime } from "@/lib/utils";

/**
 * Antigüedad del dato que el usuario está viendo, en un solo sitio.
 *
 * Antes había dos indicadores simultáneos que respondían a preguntas
 * distintas y podían discrepar en pantalla: la sidebar leía
 * `last_scrape_hours_ago` de `/analytics/quality` (cuándo terminó el último
 * *run* del scraper) y el TopNav leía `/meta/last-extraction`
 * (`MAX(fecha_extraccion)`, cuándo se selló el dato). Un run que no encuentra
 * nada nuevo mueve el primero y no el segundo.
 *
 * El titular de producto es el segundo: "cómo de fresco es lo que estoy
 * mirando". La salud del pipeline es una pregunta de Ops y ya vive en
 * `/observabilidad` y `/calidad-datos`.
 */
export function useDataFreshness() {
  const query = useQuery({
    queryKey: ["meta", "last-extraction"],
    queryFn: () => apiGet("/api/v1/meta/last-extraction"),
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
    retry: 1,
  });

  const lastExtraction = query.data?.last_extraction ?? null;

  return {
    /** Instante ISO del último sellado de dato, o `null` si aún no se sabe. */
    lastExtraction,
    /** "hace 3 horas", "ayer", … o `null` mientras no haya dato. */
    relative: lastExtraction ? formatRelativeTime(lastExtraction) : null,
    isLoading: query.isLoading,
  };
}
