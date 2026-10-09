"use client";

/**
 * Datos de la vista Estado: el health del servicio, ya leído.
 *
 * Refresca cada 30 s porque la pantalla se deja abierta como panel de guardia;
 * `dataUpdatedAt` es lo que da la hora del último chequeo, y por eso sale de
 * aquí ya convertido a `Date` en vez de dejar el epoch suelto en el JSX.
 *
 * El recuento de la cola de errores ya no se pide aquí: lo lleva la tira de
 * salud, que está encima de todas las vistas, y repetirlo en un panel propio
 * era el mismo número por tercera vez.
 */

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { adminKeys } from "@/lib/query-keys";
import {
  componentesDeSalud,
  estadoGlobal,
  type ComponenteSalud,
  type EstadoGlobalSalud,
  type HealthResponse,
} from "../_components/observabilidad/health-checks";

const REFRESCO_MS = 30_000;

export interface Observabilidad {
  health: HealthResponse | undefined;
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  refetch: () => void;
  /** Momento del último health que llegó, o `null` si aún no llegó ninguno. */
  lastCheck: Date | null;
  /** Lo que dice la API de sí misma (`status`), no si la llamada fue bien. */
  estado: EstadoGlobalSalud;
  componentes: ComponenteSalud[];
}

export function useObservabilidad(): Observabilidad {
  const {
    data: health,
    isLoading,
    isError,
    isFetching,
    dataUpdatedAt,
    refetch,
  } = useQuery<HealthResponse>({
    queryKey: adminKeys.health,
    queryFn: () => fetchWithAuth<HealthResponse>("/api/v1/health"),
    refetchInterval: REFRESCO_MS,
    // La caída se pinta en la pantalla (cabecera y «Estado del sistema»): sin
    // esto, con la API caída saltaba un toast cada 30 s.
    meta: META_ERROR_EN_LINEA,
  });

  return {
    health,
    isLoading,
    isError,
    isFetching,
    refetch: () => void refetch(),
    lastCheck: dataUpdatedAt ? new Date(dataUpdatedAt) : null,
    estado: estadoGlobal(health, { cargando: isLoading, fallo: isError }),
    componentes: componentesDeSalud(health),
  };
}
