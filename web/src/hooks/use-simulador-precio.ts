"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import type { EscenarioPuntos, SimulacionPrecio } from "@/lib/api-types";
import { simuladorKeys } from "@/lib/query-keys";

export type { EscenarioPuntos, SimulacionPrecio };

/**
 * F2.2 — puntos de precio que da cada baja según la fórmula del pliego.
 *
 * `bajas` va en tanto por uno (0.12 = 12 %), igual que en la API. Vacía, el
 * backend simula sus escenarios de referencia (5/10/15/20/25 %): no se repiten
 * aquí para que las dos pantallas que hablan de bajas no diverjan.
 *
 * La respuesta es 200 también cuando no se puede calcular (`sin_calculo`), así
 * que un error aquí es un fallo de verdad, no «el pliego no trae fórmula».
 */
export function useSimuladorPrecio(
  licitacionId: string | null,
  bajas: readonly number[] = [],
  bajaReferencia: number | null = null,
) {
  return useQuery({
    queryKey: simuladorKeys.detail(licitacionId ?? "", bajas, bajaReferencia),
    queryFn: () => {
      const query = new URLSearchParams();
      for (const baja of bajas) query.append("baja", String(baja));
      if (bajaReferencia != null) query.set("baja_referencia", String(bajaReferencia));
      const qs = query.toString();
      return fetchWithAuth<SimulacionPrecio>(
        `/api/v1/licitaciones/${encodeURIComponent(licitacionId!)}/simulador${qs ? `?${qs}` : ""}`,
      );
    },
    enabled: Boolean(licitacionId),
    staleTime: 5 * 60_000,
    // Mientras se teclea otra baja, la tabla anterior sigue visible en vez de
    // parpadear a un esqueleto en cada pulsación.
    placeholderData: (anterior) => anterior,
  });
}
