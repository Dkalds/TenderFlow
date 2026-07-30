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

function pursuitQuery(filters: PursuitFilters): string {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.responsible_user_id) params.set("responsible_user_id", String(filters.responsible_user_id));
  const search = params.toString();
  return search ? `?${search}` : "";
}

export function usePursuits(filters: PursuitFilters = {}) {
  const organizationId = useActiveOrganizationId();
  const query = pursuitQuery(filters);
  const separator = query ? "&" : "?";
  const organizationQuery = organizationId
    ? `${query}${separator}organization_id=${organizationId}`
    : query;
  return useQuery({
    queryKey: [...pursuitKeys.list(filters), organizationId],
    queryFn: () => fetchWithAuth<PursuitList>(`/api/v1/pursuits${organizationQuery}`),
    enabled: organizationId !== null,
    staleTime: 30_000,
  });
}

export function usePursuit(id: string | null) {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: [...pursuitKeys.detail(id ?? ""), organizationId],
    queryFn: () =>
      fetchWithAuth<Pursuit>(
        `/api/v1/pursuits/${encodeURIComponent(id!)}?organization_id=${organizationId}`,
      ),
    enabled: Boolean(id) && organizationId !== null,
  });
}

function invalidatePursuits(queryClient: ReturnType<typeof useQueryClient>) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: pursuitKeys.all }),
    queryClient.invalidateQueries({ queryKey: pursuitKeys.metrics }),
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
    mutationFn: (input: UpdatePursuitInput) =>
      apiMutate<Pursuit>(
        "PATCH",
        `/api/v1/pursuits/${encodeURIComponent(pursuitId)}?organization_id=${organizationId}`,
        input,
      ),
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
    queryFn: () =>
      fetchWithAuth<PursuitMetrics>(
        `/api/v1/pursuits/metrics?organization_id=${organizationId}`,
      ),
    enabled: organizationId !== null,
    staleTime: 60_000,
  });
}
