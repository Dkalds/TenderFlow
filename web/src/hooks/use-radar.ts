"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import type { components } from "@/generated/api";

/**
 * Proyección que renderiza el Radar.
 *
 * Se deriva del esquema generado, no se escribe a mano: un campo que la API no
 * envía deja de compilar aquí en vez de aparecer como `undefined` en pantalla.
 */
type LicitacionSummary = components["schemas"]["LicitacionSummary"];
type ScoredOpportunity = components["schemas"]["ScoredOpportunity"];

export type RadarTender = LicitacionSummary & {
  score?: number | null;
  band?: string | null;
};

/** Lo que devuelve el listado: sin `score` ni `band`, que llegan del scoring. */
interface ListingResponse {
  items: LicitacionSummary[];
}

interface ScoringResponse {
  opportunities: ScoredOpportunity[];
}

/**
 * `sort` sin prefijo es descendente para fechas (lo más reciente primero); el
 * prefijo `-` invierte a ascendente. Es al revés que en `importe`, así que
 * pedir `-fecha_publicacion` devolvía las licitaciones más viejas de la base
 * — justo lo contrario de un radar.
 *
 * `tecnologia` es un filtro único (o `null` para "Todas"). Radar se apoya en
 * el listado existente y le alinea el score por id, igual que la página de
 * detalle. El scoring lo calcula el backend (ADR-014): aquí sólo se
 * emparejan ids y se ordena por el valor recibido, nunca se deriva una
 * puntuación en cliente.
 *
 * **Alcance real de la lista** (la UI debe decirlo, ver `radar/page.tsx`): son
 * las 24 licitaciones *más recientes*, reordenadas por score. No es el top-24
 * por score de todo el corpus. Antes se renderizaban en orden cronológico
 * mientras la página prometía priorización, que es el anti-patrón 1 de
 * `docs/frontend-data-invariants.md` aplicado al orden en vez de al número.
 *
 * El ranking real ya existe en backend (`GET /analytics/scoring?limit=N`
 * devuelve "ranked by commercial potential"), pero su DTO `ScoredOpportunity`
 * no incluye `fecha_limite` ni `tecnologia`, que la tarjeta necesita, y el
 * único endpoint de hidratación por ids (`POST /licitaciones/bulk-get`) exige
 * API key en vez de sesión. Cambiar a esa fuente es P1 en
 * `docs/IMPROVEMENT_BACKLOG.md`.
 */
export function useRadar(tecnologia: string | null = null) {
  const params = new URLSearchParams({
    limit: "24",
    with_total: "false",
    sort: "fecha_publicacion",
  });
  if (tecnologia) params.set("tecnologia", tecnologia);

  const listing = useQuery({
    queryKey: ["radar", "tenders", tecnologia],
    queryFn: () => fetchWithAuth<ListingResponse>(`/api/v1/licitaciones?${params.toString()}`),
    staleTime: 30_000,
  });

  const ids = (listing.data?.items ?? []).map((item) => item.id_externo).filter(Boolean);

  const scoring = useQuery({
    queryKey: ["radar", "scoring", ids],
    queryFn: () =>
      fetchWithAuth<ScoringResponse>(
        `/api/v1/analytics/scoring?ids=${encodeURIComponent(ids.join(","))}`,
      ),
    enabled: ids.length > 0,
    staleTime: 5 * 60_000,
    placeholderData: (previous) => previous,
  });

  const scores = new Map(
    (scoring.data?.opportunities ?? []).map((row) => [row.id_externo, row] as const),
  );

  const items: RadarTender[] = (listing.data?.items ?? [])
    .map<RadarTender>((item) => {
      const scored = scores.get(item.id_externo);
      return scored ? { ...item, score: scored.score, band: scored.band } : item;
    })
    // Orden por el score que devolvió el backend, descendente; los que no tienen
    // score van al final conservando su orden de publicación. Sin `score` aún en
    // vuelo el orden es el del listado, y la UI lo señala como "ordenando…" en
    // vez de fingir que ya está priorizado.
    .sort((a, b) => (b.score ?? -1) - (a.score ?? -1));

  return {
    data: listing.data ? { items } : undefined,
    isLoading: listing.isLoading,
    /** El score aún no ha llegado: el orden mostrado todavía no es el final. */
    isRanking: scoring.isPending && ids.length > 0,
    error: listing.error,
  };
}
