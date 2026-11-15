"use client";

/**
 * Feature flags desde Administración: la lista y el guardado de lo que cambió.
 *
 * Comparte la clave con `useFeatureFlag` (`hooks/use-feature-flag.ts`), que es
 * quien las lee en el resto de la consola: al guardar, una flag apagada se nota
 * al momento. Las opciones no se comparten: aquí el fallo se dice en el panel y
 * se reintenta; allí es fail-open y silencioso.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiMutate } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { featureFlagKeys } from "@/lib/query-keys";
import { toast } from "@/lib/toast";

export type FlagOut = Schemas["FlagOut"];
/** Lo que se guarda de una flag: su nombre y el ajuste que queda. */
export type CambioFlag = Pick<FlagOut, "flag" | "enabled" | "rollout_pct">;

export function useFeatureFlagsAdmin() {
  return useQuery<FlagOut[]>({
    queryKey: featureFlagKeys.list,
    queryFn: () => apiGet("/api/v1/feature-flags"),
    // El fallo lo dice el panel: sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });
}

/** Guarda solo las flags que difieren del servidor (las decide quien llama). */
export function useGuardarFeatureFlags() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (cambios: CambioFlag[]) => apiMutate("PUT", "/api/v1/feature-flags", { flags: cambios }),
    onSuccess: (_respuesta, cambios) => {
      // Lo guardado pasa a ser «lo del servidor» antes de soltar el borrador:
      // sin esto la lista volvía un instante a los valores viejos mientras
      // llegaba la relectura.
      const guardadas = new Map(cambios.map((cambio) => [cambio.flag, cambio]));
      queryClient.setQueryData<FlagOut[]>(featureFlagKeys.list, (previas) =>
        previas?.map((flag) => ({ ...flag, ...guardadas.get(flag.flag) })),
      );
      void queryClient.invalidateQueries({ queryKey: featureFlagKeys.all });
      toast.success("Cambios guardados");
    },
  });
}
