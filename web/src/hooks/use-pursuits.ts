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
import { primeraVez, registrarEvento } from "@/lib/analytics";
import {
  organizacionResuelta,
  useActiveOrganizationId,
  type OrganizacionActiva,
} from "@/hooks/use-organization";
import type {
  PipelineAgendaItem as PipelineAgendaItemDTO,
  PipelineAgendaResponse,
  PursuitCreate,
  PursuitDetail,
  PursuitListResponse,
  PursuitMetrics as PursuitMetricsDTO,
  PursuitUpdate,
} from "@/lib/api-types";
import { organizationKeys } from "@/lib/query-keys";
import { pursuitKeys } from "@/lib/query-keys";

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

/**
 * Los tres estados de los que una oportunidad ya no sale por su cuenta. Vive
 * aquí, junto al orden del workflow, y no en la pantalla del tablero: la
 * tarjeta y la ficha también necesitan saber si algo está cerrado.
 */
export const ESTADOS_TERMINALES = [
  "won",
  "lost",
  "withdrawn",
] as const satisfies readonly PursuitStatus[];

export type EstadoTerminal = (typeof ESTADOS_TERMINALES)[number];

export function esTerminal(status: PursuitStatus): status is EstadoTerminal {
  return (ESTADOS_TERMINALES as readonly PursuitStatus[]).includes(status);
}

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

export { pursuitKeys } from "@/lib/query-keys";

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
  organizationId: OrganizacionActiva,
): Record<string, ApiQueryValue> {
  return {
    status: filters.status,
    responsible_user_id: filters.responsible_user_id || undefined,
    organization_id: organizationId ?? undefined,
  };
}

/** Query común a las vistas de organización que van por el cliente tipado. */
function organizationQuery(organizationId: OrganizacionActiva): Record<string, ApiQueryValue> {
  return { organization_id: organizationId ?? undefined };
}

/**
 * `organizationId === null` no significa "sin datos": el backend resuelve la
 * organización personal automáticamente cuando se omite el parámetro. Por eso
 * una organización resuelta a `null` **sí** lanza la consulta, en vez de
 * quedarse deshabilitada esperando un id explícito.
 *
 * Lo que no se puede hacer es lanzarla antes de saberlo (`undefined`), que es
 * distinto: `/organizations` sigue en vuelo y preguntar ya significa preguntar
 * por la personal. En un listado eso era un parpadeo con las oportunidades de
 * otra organización; en `usePursuit` era un 404 con toast rojo en cada apertura
 * de ficha, corregido medio segundo después por la petición buena. De ahí el
 * `organizacionResuelta` de cada `enabled`.
 */
export function usePursuits(filters: PursuitFilters = {}) {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: [...pursuitKeys.list(filters), organizationId],
    queryFn: () =>
      apiGet("/api/v1/pursuits", { params: { query: pursuitQuery(filters, organizationId) } }),
    enabled: organizacionResuelta(organizationId),
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
    enabled: Boolean(id) && organizacionResuelta(organizationId),
  });
}

function invalidatePursuits(queryClient: ReturnType<typeof useQueryClient>) {
  // `pursuitKeys.all` es prefijo de `metrics` y `agenda`, así que una sola
  // invalidación cubre listados, métricas y la agenda de Mi Pipeline.
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: pursuitKeys.all }),
    queryClient.invalidateQueries({ queryKey: organizationKeys.all }),
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
    onSuccess: () => {
      // Activación: el salto de mirar el mercado a trabajar una oportunidad.
      // Ni el id del pursuit ni el de la organización entran en el evento — el
      // hecho es "alguien se comprometió", no "quién con qué".
      registrarEvento("pursuit_creado", { primera_vez: primeraVez("pursuit") });
      return invalidatePursuits(queryClient);
    },
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
    onSuccess: (pursuit, input) => {
      // ¿El pipeline se mueve, o se abandona en cuanto se crea? Sólo cuando el
      // parche toca el estado: un PATCH de precio o de responsable no es un
      // avance del workflow y contarlo como tal enmascararía el abandono.
      // F3.1: al cerrar como perdida viaja el motivo codificado (lista cerrada
      // de D37, categórica); la nota de texto libre nunca sale de aquí.
      if (input.status) {
        registrarEvento("pursuit_estado_cambiado", {
          estado: input.status,
          ...(input.status === "lost" && input.outcome_reason_code
            ? { motivo: input.outcome_reason_code }
            : {}),
        });
      }
      // La misma clave que lee `usePursuit`, organización incluida: sin ella el
      // detalle se sembraba en una entrada que nadie consulta y la vista se
      // quedaba esperando al refetch de la invalidación.
      queryClient.setQueryData([...pursuitKeys.detail(pursuitId), organizationId], pursuit);
      return invalidatePursuits(queryClient);
    },
  });
}

/**
 * Mover una oportunidad de fase desde el tablero.
 *
 * `useUpdatePursuit` liga el id al hook, y el tablero no sabe cuál va a
 * arrastrar el usuario hasta que la suelta. Esta variante recibe el id en la
 * mutación; a cambio comparte con aquélla el evento de analítica y la misma
 * invalidación, para que mover una tarjeta y cambiar el estado desde la ficha
 * cuenten igual en el embudo.
 *
 * `expected_version` viaja siempre. Un tablero es de equipo: si alguien movió
 * la misma tarjeta mientras ésta estaba en el aire, el backend rechaza el PATCH
 * en vez de pisar su cambio, y la pantalla deshace su movimiento optimista.
 */
export function useMoverPursuit() {
  const queryClient = useQueryClient();
  const organizationId = useActiveOrganizationId();
  return useMutation({
    mutationFn: ({ id, ...input }: UpdatePursuitInput & { id: string | number }) => {
      const params = new URLSearchParams();
      if (organizationId != null) params.set("organization_id", String(organizationId));
      const query = params.toString();
      return apiMutate<Pursuit>(
        "PATCH",
        `/api/v1/pursuits/${encodeURIComponent(String(id))}${query ? `?${query}` : ""}`,
        input,
      );
    },
    onSuccess: (pursuit, variables) => {
      if (variables.status) {
        registrarEvento("pursuit_estado_cambiado", {
          estado: variables.status,
          ...(variables.status === "lost" && variables.outcome_reason_code
            ? { motivo: variables.outcome_reason_code }
            : {}),
        });
      }
      queryClient.setQueryData(
        [...pursuitKeys.detail(String(variables.id)), organizationId],
        pursuit,
      );
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
    enabled: organizacionResuelta(organizationId),
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
    enabled: organizacionResuelta(organizationId),
    staleTime: 30_000,
  });
}
