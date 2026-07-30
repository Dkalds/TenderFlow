"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";

/** A deliberately small projection used by the action-oriented Radar. */
export interface RadarTender {
  id_externo: string;
  titulo: string | null;
  organo_contratacion: string | null;
  importe: number | null;
  fecha_limite: string | null;
  fecha_publicacion: string | null;
  estado: string | null;
  tecnologia: string | null;
  score?: number | null;
  band?: string | null;
}

interface RadarResponse {
  items: RadarTender[];
  total: number;
}

/**
 * Radar is intentionally based on the existing tender listing.  It therefore
 * works before personalised ranking is introduced, while the endpoint remains
 * a stable place to attach that ranking later.
 */
export function useRadar() {
  return useQuery({
    queryKey: ["radar", "tenders"],
    queryFn: () =>
      fetchWithAuth<RadarResponse>(
        "/api/v1/licitaciones?limit=24&with_total=false&sort=-fecha_publicacion",
      ),
    staleTime: 30_000,
  });
}
