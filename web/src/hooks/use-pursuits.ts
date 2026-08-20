"use client";

/**
 * Product workflow API for an organisation's pursuits.
 *
 * Los tipos se derivan del esquema OpenAPI generado, no se copian a mano: un
 * campo que la API deja de enviar (o que nunca envió) rompe el typecheck aquí
 * en vez de llegar a la pantalla como `undefined`.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiMutate, fetchWithAuth, type ApiQueryValue } from "@/lib/api-client";
import { useActiveOrganizationId } from "@/hooks/use-organization";
import type {
  PipelineAgendaItem as PipelineAgendaItemDTO,
  PipelineAgendaResponse,
  PursuitCreate,
  PursuitDetail,
  PursuitListResponse,
  PursuitMetrics as PursuitMetricsDTO,
  PursuitUpdate,
} from "@/lib/api-types";

export type Pursuit = PursuitDetail;
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
export type PursuitList = PursuitListResponse;
export type PursuitMetrics = PursuitMetricsDTO;
export type CreatePursuitInput = PursuitCreate;
export type UpdatePursuitInput = PursuitUpdate;
export type PipelineAgenda = PipelineAgendaResponse;
export type PipelineAgendaItem = PipelineAgendaItemDTO;
export type AgendaUrgencia = PipelineAgendaItem["urgencia"];
export type AgendaKind = PipelineAgendaItem["kind"];

export const pursuitKeys = {
  all: ["pursuits"] as const,
  list: (filters: PursuitFilters) => ["pursuits", "list", filters] as const,
  detail: (id: string) => ["pursuits", "detail", id] as const,
  metrics: ["pursuits", "metrics"] as const,
  agenda: ["pursuits", "agenda"] as const,
};

export interface PursuitFilters {
  status?: PursuitStatus;
  responsible_user_id?: number;
}

/**
 * Query del listado. Los valores `undefined` los descarta el serializador del
 * cliente tipado, así que esto equivale al `if (x) params.set(...)` anterior.
 */
function pursuitQuery(
  filters: PursuitFilters,
  organizationId: number | null,
): Record<string, ApiQueryValue> {
  return {
    status: filters.status,
    responsible_user_id: filters.responsible_user_id || undefined,
    organization_id: organizationId ?? undefined,
  };
}

/** Query común a las vistas de organización que van por el cliente tipado. */
function organizationQuery(organizationId: number | null): Record<string, ApiQueryValue> {
  return { organization_id: organizationId ?? undefined };
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
      apiGet("/api/v1/pursuits", { params: { query: pursuitQuery(filters, organizationId) } }),
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
  // `pursuitKeys.all` es prefijo de `metrics` y `agenda`, así que una sola
  // invalidación cubre listados, métricas y la agenda de Mi Pipeline.
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: pursuitKeys.all }),
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
    queryFn: () =>
      apiGet("/api/v1/pursuits/metrics", { params: { query: organizationQuery(organizationId) } }),
    staleTime: 60_000,
  });
}

export interface AgendaFilters {
  soloMios: boolean;
  tecnologia: string | null;
  ccaa: string | null;
}

/**
 * Agenda de compromisos de Mi Pipeline.
 *
 * La fusión (pursuits + señales + renovaciones), el orden y las bandas de
 * urgencia vienen del backend; aquí solo se agrupan por la banda ya puesta.
 * El descarte de señales comparte persistencia con el Radar
 * (`/api/v1/radar/dismissals`), así que sus mutaciones invalidan esta query.
 */
export function usePipelineAgenda(filters: AgendaFilters) {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: [...pursuitKeys.agenda, filters, organizationId],
    queryFn: () =>
      apiGet("/api/v1/pursuits/agenda", {
        params: {
          query: {
            ...organizationQuery(organizationId),
            // `solo_mios` solo viaja cuando está activo: el backend ya asume
            // `false` y mandarlo vacío ensuciaría la URL cacheada.
            solo_mios: filters.soloMios || undefined,
            tecnologia: filters.tecnologia || undefined,
            ccaa: filters.ccaa || undefined,
          },
        },
      }),
    staleTime: 30_000,
  });
}
