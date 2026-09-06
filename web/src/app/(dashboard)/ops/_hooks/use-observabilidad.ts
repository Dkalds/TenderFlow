"use client";

/**
 * Datos de la vista de Observabilidad: el health del servicio y el recuento de
 * DLQ que la acompaña.
 *
 * Las dos consultas refrescan cada 30 s porque la pantalla se deja abierta como
 * panel de guardia; `dataUpdatedAt` es lo que da la hora del último chequeo, y
 * por eso sale de aquí ya convertido a `Date` en vez de dejar el epoch suelto
 * en el JSX.
 */

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { adminKeys, analyticsKeys } from "@/lib/query-keys";
import {
  extraerChecks,
  type HealthResponse,
  type QualityData,
} from "../_components/observabilidad/health-checks";

export type EstadoGlobalSalud = "ok" | "warn" | "error";

const REFRESCO_MS = 30_000;

export interface Observabilidad {
  health: HealthResponse | undefined;
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  refetch: () => void;
  /** Hay respuesta y no ha fallado: la API contesta. */
  isOnline: boolean;
  /** Momento del último health que llegó, o `null` si aún no llegó ninguno. */
  lastCheck: Date | null;
  estado: EstadoGlobalSalud;
  checks: Record<string, unknown>;
  dlqCount: number;
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
  });

  const { data: quality } = useQuery<QualityData>({
    queryKey: analyticsKeys.quality,
    queryFn: () => fetchWithAuth<QualityData>("/api/v1/analytics/quality"),
    refetchInterval: REFRESCO_MS,
  });

  const isOnline = !!health && !isError;

  return {
    health,
    isLoading,
    isError,
    isFetching,
    refetch: () => void refetch(),
    isOnline,
    lastCheck: dataUpdatedAt ? new Date(dataUpdatedAt) : null,
    estado: isLoading ? "warn" : isOnline ? "ok" : "error",
    checks: extraerChecks(health),
    dlqCount: quality?.dlq_count ?? 0,
  };
}
