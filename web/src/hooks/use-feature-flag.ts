"use client";

/**
 * Lectura de feature flags desde el producto.
 *
 * # Por qué existe
 *
 * Las flags se administraban en `/ops` (`ops/_components/feature-flags-view.tsx`)
 * y **ninguna vista las leía**: fuera de `ops/` la palabra sólo aparecía como
 * nombre de ruta heredada en `lib/navigation.ts` y `lib/space-views.ts`. Un
 * panel de toggles que no apaga nada es peor que no tenerlo — promete un
 * control que no existe.
 *
 * # La regla que gobierna este hook: FAIL-OPEN
 *
 * Una flag que no se puede resolver **no esconde la vista**. Si la API de flags
 * no responde, devuelve un error, o simplemente no conoce todavía el nombre
 * pedido (la tabla `feature_flags` se llena desde `/ops`, no viene sembrada),
 * la respuesta es `enabled: true` con `estado: "sin_respuesta"`.
 *
 * El motivo es de producto, no de comodidad: la alternativa —fail-closed— hace
 * que una caída del backend de flags borre pantallas que funcionan, y que una
 * vista nueva sea invisible hasta que alguien se acuerde de crear su fila. Una
 * vista experimental ya se anuncia como tal; ocultarla por no saber es la peor
 * de las dos equivocaciones posibles.
 *
 * Lo único que apaga algo es un **no** explícito del backend: la fila existe y
 * dice `enabled: false`.
 *
 * # Lo que este hook NO hace
 *
 * No evalúa `rollout_pct`. Un rollout parcial exige un bucket estable por
 * usuario, y el contrato (`FlagOut`) no trae la decisión ya tomada para quien
 * pregunta: emularla en cliente sería inventarse a quién le toca. Mientras el
 * backend no responda «esta flag está activa *para ti*», aquí manda `enabled`.
 */

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";

type FlagOut = Schemas["FlagOut"];

/**
 * Clave de React Query de la lista de flags.
 *
 * La convención del repo es declararla en `lib/query-keys.ts`; vive aquí
 * porque ese fichero pertenece a otro lote de este mismo refactor. Es una sola
 * clave para una sola `queryFn` —el problema que `query-keys.ts` existe para
 * evitar—, así que mover la constante allí es una línea sin cambio de
 * comportamiento.
 */
export const featureFlagKeys = {
  all: ["feature-flags"] as const,
  list: ["feature-flags", "list"] as const,
};

/**
 * Qué sabe el frontend de una flag.
 *
 * - `activo`: la fila existe y está encendida.
 * - `inactivo`: la fila existe y está apagada. **El único caso que apaga algo.**
 * - `sin_respuesta`: cargando, la API falló, o el backend no conoce el nombre.
 *   Fail-open: la superficie se pinta igual.
 */
export type EstadoFlag = "activo" | "inactivo" | "sin_respuesta";

export interface FeatureFlagState {
  /** `false` sólo cuando el backend dice explícitamente que no. */
  enabled: boolean;
  estado: EstadoFlag;
  /** La primera petición sigue en vuelo. La vista ya es visible (fail-open). */
  isLoading: boolean;
}

/**
 * Lista de flags del backend. Una sola petición compartida por todos los
 * `useFeatureFlag` montados a la vez (misma `queryKey`).
 *
 * `retry: false` es deliberado: con fail-open, reintentar sólo retrasa la
 * confirmación de algo que ya se está pintando.
 */
function useFeatureFlags() {
  return useQuery<FlagOut[]>({
    queryKey: featureFlagKeys.list,
    queryFn: () => apiGet("/api/v1/feature-flags"),
    staleTime: 5 * 60_000,
    retry: false,
    // Un fallo de flags no es un incidente que deba llenar la consola de
    // errores: es el camino previsto por el fail-open.
    meta: { silent: true },
  });
}

/**
 * ¿Está encendida la flag `name`?
 *
 * @example
 * const { enabled, estado } = useFeatureFlag("mercado_clusters");
 * if (!enabled) return <VistaApagada />;
 */
export function useFeatureFlag(name: string): FeatureFlagState {
  const { data, isLoading, isError } = useFeatureFlags();

  if (isLoading || isError || data == null) {
    return { enabled: true, estado: "sin_respuesta", isLoading };
  }

  const flag = data.find((candidate) => candidate.flag === name);
  if (flag == null) {
    // El backend respondió y no conoce el nombre: sigue siendo "no sé", no un
    // "no". La fila se crea desde `/ops` cuando alguien quiera apagarla.
    return { enabled: true, estado: "sin_respuesta", isLoading: false };
  }

  return {
    enabled: flag.enabled,
    estado: flag.enabled ? "activo" : "inactivo",
    isLoading: false,
  };
}
