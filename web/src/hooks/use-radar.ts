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
 *
 * `tecnologia` es un filtro único (o `null` para "Todas"). El orden pide
 * explícitamente `fecha_publicacion`: en este repositorio el prefijo `-`
 * invierte el sentido intuitivo (ascendente), así que usarlo aquí mostraba
 * las señales más antiguas en vez de las recientes.
 */
export function useRadar(tecnologia: string | null = null) {
  const params = new URLSearchParams({
    limit: "24",
    with_total: "false",
    sort: "fecha_publicacion",
  });
  if (tecnologia) params.set("tecnologia", tecnologia);

  return useQuery({
    queryKey: ["radar", "tenders", tecnologia],
    queryFn: () => fetchWithAuth<RadarResponse>(`/api/v1/licitaciones?${params.toString()}`),
    staleTime: 30_000,
  });
}
