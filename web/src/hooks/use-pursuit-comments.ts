"use client";

/**
 * Hilo de comentarios de una oportunidad: el chat del equipo sobre un
 * expediente.
 *
 * Vive aparte del ledger de eventos (`pursuit.events`), que es auditoría
 * inmutable; aquí sí hay borrado (autor, o owner/admin del espacio), y la API
 * ya dice en cada comentario si quien pregunta puede borrarlo (`can_delete`),
 * así que el frontend no reimplementa la regla de moderación.
 *
 * Sin websockets: mientras el hilo está montado se vuelve a pedir cada 20 s.
 * Para un hilo por expediente y un equipo de bid es suficiente y no añade
 * infraestructura; si algún día hace falta empuje real, este hook es el único
 * sitio a cambiar.
 *
 * Sin telemetría, a propósito: «¿conversa el equipo o cada oportunidad la
 * trabaja una sola persona?» se responde mejor en backend, contando
 * `pursuit_comments` (mensajes, autores distintos, expedientes con hilo), que
 * con un evento categórico. Es la regla 1 de `lib/analytics.ts` —lo que el
 * servidor ya sabe no se mide desde el navegador— y por eso este hook no
 * gasta un hueco del catálogo.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { useActiveOrganizationId } from "@/hooks/use-organization";
import { pursuitKeys } from "@/hooks/use-pursuits";
import type {
  PursuitCommentCreate,
  PursuitCommentListResponse,
  PursuitCommentOut,
} from "@/lib/api-types";

export type PursuitComment = PursuitCommentOut;
export type PursuitCommentList = PursuitCommentListResponse;

/** Intervalo de refresco del hilo mientras está a la vista. */
export const COMMENTS_REFETCH_MS = 20_000;

/**
 * Comentarios por página. Es el máximo que admite la API; un hilo de
 * expediente no se acerca, y si algún día lo hace la respuesta lo declara en
 * `total` y el componente lo dice en vez de fingir que está entero.
 */
export const COMMENTS_PAGE_SIZE = 200;

export const pursuitCommentKeys = {
  all: ["pursuit-comments"] as const,
  thread: (pursuitId: number | string) => ["pursuit-comments", String(pursuitId)] as const,
};

export interface AddPursuitCommentInput extends PursuitCommentCreate {
  /**
   * Clave de idempotencia del envío. La genera el compositor al empezar un
   * borrador y la conserva hasta que el envío tiene éxito: reintentar tras un
   * corte de red manda la misma clave y la API devuelve el comentario ya
   * guardado en vez de duplicarlo.
   */
  idempotencyKey: string;
}

function threadUrl(
  pursuitId: number | string,
  organizationId: number | null,
  options: { suffix?: string; limit?: number } = {},
): string {
  const params = new URLSearchParams();
  if (organizationId != null) params.set("organization_id", String(organizationId));
  if (options.limit != null) params.set("limit", String(options.limit));
  const query = params.toString();
  const base = `/api/v1/pursuits/${encodeURIComponent(String(pursuitId))}/comments`;
  return `${base}${options.suffix ?? ""}${query ? `?${query}` : ""}`;
}

/**
 * Hilo de una oportunidad. `organizationId === null` no desactiva la query: el
 * backend resuelve la organización personal cuando se omite, igual que en
 * `usePursuit`.
 */
export function usePursuitComments(
  pursuitId: number | string | null,
  options: { enabled?: boolean } = {},
) {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: [...pursuitCommentKeys.thread(pursuitId ?? ""), organizationId],
    queryFn: () =>
      fetchWithAuth<PursuitCommentList>(
        threadUrl(pursuitId!, organizationId, { limit: COMMENTS_PAGE_SIZE }),
      ),
    enabled: pursuitId != null && (options.enabled ?? true),
    refetchInterval: COMMENTS_REFETCH_MS,
    staleTime: 5_000,
  });
}

function invalidateThread(queryClient: ReturnType<typeof useQueryClient>, pursuitId: number | string) {
  // El contador (`comments_count`) viaja en el listado y en la ficha de la
  // oportunidad: invalidar `pursuitKeys.all` lo pone al día en el tablero.
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: pursuitCommentKeys.thread(pursuitId) }),
    queryClient.invalidateQueries({ queryKey: pursuitKeys.all }),
  ]);
}

export function useAddPursuitComment(pursuitId: number | string) {
  const queryClient = useQueryClient();
  const organizationId = useActiveOrganizationId();
  return useMutation({
    mutationFn: ({ idempotencyKey, ...input }: AddPursuitCommentInput) =>
      fetchWithAuth<PursuitComment>(threadUrl(pursuitId, organizationId), {
        method: "POST",
        headers: { "X-Idempotency-Key": idempotencyKey },
        body: JSON.stringify(input),
      }),
    onSuccess: () => invalidateThread(queryClient, pursuitId),
  });
}

export function useDeletePursuitComment(pursuitId: number | string) {
  const queryClient = useQueryClient();
  const organizationId = useActiveOrganizationId();
  return useMutation({
    mutationFn: (commentId: number) =>
      fetchWithAuth<void>(threadUrl(pursuitId, organizationId, { suffix: `/${commentId}` }), {
        method: "DELETE",
      }),
    onSuccess: () => invalidateThread(queryClient, pursuitId),
  });
}
