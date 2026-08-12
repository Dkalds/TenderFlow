"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import type { components } from "@/generated/api";

/**
 * Proyección que renderiza el Radar.
 *
 * Se deriva del esquema generado, no se escribe a mano: un campo que la API no
 * envía deja de compilar aquí en vez de aparecer como `undefined` en pantalla.
 */
type ScoredOpportunity = components["schemas"]["ScoredOpportunity"];

export type RadarTender = ScoredOpportunity;

interface ScoringResponse {
  opportunities: ScoredOpportunity[];
}

interface DismissalsResponse {
  ids: string[];
}

const DISMISSALS_KEY = ["radar", "dismissals"] as const;

/**
 * Fuente del Radar: el ranking de mercado, no el listado reordenado.
 *
 * `GET /analytics/scoring?limit=N` devuelve el top-N por potencial comercial
 * sobre todo el corpus abierto. Antes esta lista salía de
 * `GET /licitaciones?limit=24&sort=fecha_publicacion` y se le alineaba el score
 * por id, así que eran "las 24 abiertas más recientes reordenadas" — la UI
 * prometía priorización de mercado y entregaba una ventana cronológica. El
 * cambio fue posible al añadir `fecha_limite` y `tecnologia` a
 * `ScoredOpportunity`, los dos campos que la tarjeta pinta y que obligaban a
 * rehidratar contra el listado.
 *
 * La puntuación y el orden los calcula el backend (ADR-014): aquí no se deriva
 * ninguna dimensión ni se reordena nada.
 *
 * El filtro por tecnología viaja en la query, no se aplica al ranking recibido:
 * el top-24 tiene que ser el de esa tecnología. Filtrándolo en el cliente, con
 * 13 licitaciones SAP vivas entre 1.643, el top-24 global no traía ninguna y la
 * bandeja salía vacía bajo una cabecera que prometía lo contrario.
 */
export function useRadar(tecnologia: string | null = null) {
  const params = new URLSearchParams({ limit: "24" });
  if (tecnologia) params.set("tecnologia", tecnologia);

  const scoring = useQuery({
    queryKey: ["radar", "scoring", tecnologia],
    queryFn: () =>
      fetchWithAuth<ScoringResponse>(`/api/v1/analytics/scoring?${params.toString()}`),
    staleTime: 5 * 60_000,
  });

  const items: RadarTender[] = scoring.data?.opportunities ?? [];

  return {
    data: scoring.data ? { items } : undefined,
    isLoading: scoring.isPending,
    error: scoring.error,
    refetch: scoring.refetch,
  };
}

/** Señales que el usuario descartó, persistidas server-side. */
export function useRadarDismissals() {
  return useQuery({
    queryKey: DISMISSALS_KEY,
    queryFn: () =>
      fetchWithAuth<DismissalsResponse>("/api/v1/radar/dismissals").then(
        (response) => response.ids,
      ),
    staleTime: 60_000,
  });
}

/**
 * Descartar / deshacer, con actualización optimista.
 *
 * El descarte vivía en `React.useState`: el usuario triaba 24 señales,
 * recargaba, y volvían las 24 (invariante 2 de `frontend-data-invariants.md`).
 */
export function useDismissRadarTender() {
  const qc = useQueryClient();
  return useMutation<string[], unknown, string, { previous: string[] | undefined }>({
    mutationFn: (idExterno: string) =>
      apiMutate<DismissalsResponse>("POST", "/api/v1/radar/dismissals", {
        id_externo: idExterno,
      }).then((response) => response.ids),
    onMutate: async (idExterno: string) => {
      await qc.cancelQueries({ queryKey: DISMISSALS_KEY });
      const previous = qc.getQueryData<string[]>(DISMISSALS_KEY);
      qc.setQueryData<string[]>(DISMISSALS_KEY, (old) => [idExterno, ...(old ?? [])]);
      return { previous };
    },
    onError: (_err, _idExterno, ctx) => {
      qc.setQueryData(DISMISSALS_KEY, ctx?.previous);
      toast.error("No se pudo descartar la señal");
    },
    onSuccess: (ids: string[]) => {
      qc.setQueryData<string[]>(DISMISSALS_KEY, ids);
    },
  });
}

export function useRestoreRadarTender() {
  const qc = useQueryClient();
  return useMutation<void, unknown, string, { previous: string[] | undefined }>({
    mutationFn: (idExterno: string) =>
      apiMutate<void>(
        "DELETE",
        `/api/v1/radar/dismissals/${encodeURIComponent(idExterno)}`,
      ),
    onMutate: async (idExterno: string) => {
      await qc.cancelQueries({ queryKey: DISMISSALS_KEY });
      const previous = qc.getQueryData<string[]>(DISMISSALS_KEY);
      qc.setQueryData<string[]>(DISMISSALS_KEY, (old) =>
        (old ?? []).filter((id) => id !== idExterno),
      );
      return { previous };
    },
    onError: (_err, _idExterno, ctx) => {
      qc.setQueryData(DISMISSALS_KEY, ctx?.previous);
      toast.error("No se pudo recuperar la señal");
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: DISMISSALS_KEY });
    },
  });
}
