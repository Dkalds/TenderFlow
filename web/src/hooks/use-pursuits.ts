"use client";

/**
 * Product workflow API for an organisation's pursuits.
 *
 * Los tipos se derivan del esquema OpenAPI generado, no se copian a mano: un
 * campo que la API deja de enviar (o que nunca envió) rompe el typecheck aquí
 * en vez de llegar a la pantalla como `undefined`.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import { useActiveOrganizationId } from "@/hooks/use-organization";
import type { components } from "@/generated/api";

export type Pursuit = components["schemas"]["PursuitDetail"];
export type PursuitStatus = Pursuit["status"];

/** Orden del workflow. `satisfies` la ancla al esquema: un estado que el backend
 *  renombre o retire deja de compilar aquí. */
export const PURSUIT_STATUSES = [
  "identified",
  "qualifying",
  "go_no_go",
  "preparing",
  "submitted",
  "won",
  "lost",
  "withdrawn",
] as const satisfies readonly PursuitStatus[];

export type PursuitDecision = Pursuit["decision"];
export type PursuitOutcome = Pursuit["outcome"];
export type PursuitList = components["schemas"]["PursuitListResponse"];
export type PursuitMetrics = components["schemas"]["PursuitMetrics"];
export type CreatePursuitInput = components["schemas"]["PursuitCreate"];
export type UpdatePursuitInput = components["schemas"]["PursuitUpdate"];

export const pursuitKeys = {
  all: ["pursuits"] as const,
  list: (filters: PursuitFilters) => ["pursuits", "list", filters] as const,
  detail: (id: string) => ["pursuits", "detail", id] as const,
  metrics: ["pursuits", "metrics"] as const,
};

export interface PursuitFilters {
  status?: PursuitStatus;
  responsible_user_id?: number;
}

function pursuitQuery(filters: PursuitFilters, organizationId: number | null): string {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.responsible_user_id) params.set("responsible_user_id", String(filters.responsible_user_id));
  if (organizationId != null) params.set("organization_id", String(organizationId));
  const search = params.toString();
  return search ? `?${search}` : "";
}

/**
 * `organizationId === null` no significa "sin datos": el backend resuelve la
 * organización personal automáticamente cuando se omite el parámetro. Por eso
 * estas queries se ejecutan siempre, en vez de quedar deshabilitadas hasta que
 * exista un ID explícito seleccionado en el frontend.
 */
export function usePursuits(filters: PursuitFilters = {}) {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: [...pursuitKeys.list(filters), organizationId],
    queryFn: () =>
      fetchWithAuth<PursuitList>(`/api/v1/pursuits${pursuitQuery(filters, organizationId)}`),
    staleTime: 30_000,
  });
}

export function usePursuit(id: string | null) {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: [...pursuitKeys.detail(id ?? ""), organizationId],
    queryFn: () => {
      const params = new URLSearchParams();
      if (organizationId != null) params.set("organization_id", String(organizationId));
      const query = params.toString();
      return fetchWithAuth<Pursuit>(
        `/api/v1/pursuits/${encodeURIComponent(id!)}${query ? `?${query}` : ""}`,
      );
    },
    enabled: Boolean(id),
  });
}

function invalidatePursuits(queryClient: ReturnType<typeof useQueryClient>) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: pursuitKeys.all }),
    queryClient.invalidateQueries({ queryKey: pursuitKeys.metrics }),
    queryClient.invalidateQueries({ queryKey: ["organizations"] }),
  ]);
}

export function useCreatePursuit() {
  const queryClient = useQueryClient();
  const organizationId = useActiveOrganizationId();
  return useMutation({
    mutationFn: (input: CreatePursuitInput) =>
      apiMutate<Pursuit>("POST", "/api/v1/pursuits", {
        ...input,
        organization_id: input.organization_id ?? organizationId ?? undefined,
      }),
    onSuccess: () => invalidatePursuits(queryClient),
  });
}

export function useUpdatePursuit(id: string | number) {
  const queryClient = useQueryClient();
  const pursuitId = String(id);
  const organizationId = useActiveOrganizationId();
  return useMutation({
    mutationFn: (input: UpdatePursuitInput) => {
      const params = new URLSearchParams();
      if (organizationId != null) params.set("organization_id", String(organizationId));
      const query = params.toString();
      return apiMutate<Pursuit>(
        "PATCH",
        `/api/v1/pursuits/${encodeURIComponent(pursuitId)}${query ? `?${query}` : ""}`,
        input,
      );
    },
    onSuccess: (pursuit) => {
      // La misma clave que lee `usePursuit`, organización incluida: sin ella el
      // detalle se sembraba en una entrada que nadie consulta y la vista se
      // quedaba esperando al refetch de la invalidación.
      queryClient.setQueryData([...pursuitKeys.detail(pursuitId), organizationId], pursuit);
      return invalidatePursuits(queryClient);
    },
  });
}

export function usePursuitMetrics() {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: [...pursuitKeys.metrics, organizationId],
    queryFn: () => {
      const params = new URLSearchParams();
      if (organizationId != null) params.set("organization_id", String(organizationId));
      const query = params.toString();
      return fetchWithAuth<PursuitMetrics>(`/api/v1/pursuits/metrics${query ? `?${query}` : ""}`);
    },
    staleTime: 60_000,
  });
}
