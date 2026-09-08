"use client";

/**
 * Adjuntos propios de una oportunidad (C6.3).
 *
 * Son los documentos del **equipo** —la memoria técnica, el DEUC, el aval, los
 * borradores— frente a los del órgano, que ya vivían en `DocumentosBlock`. La
 * distinción no es decorativa: estos no los indexa el asistente salvo que
 * alguien lo autorice fichero a fichero, y la descarga va por un enlace firmado
 * con caducidad en vez de por la sesión.
 *
 * La subida manda el fichero **en crudo** con su tipo en `Content-Type` y su
 * nombre en `?filename=`. No es `multipart/form-data` porque la API no declara
 * `python-multipart`; un `body: File` es además lo que `fetch` manda sin
 * envolver, así que el cliente no arma nada.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { useActiveOrganizationId } from "@/hooks/use-organization";
import type {
  PursuitAttachmentDownloadLink,
  PursuitAttachmentListResponse,
  PursuitAttachmentOut,
} from "@/lib/api-types";
import { pursuitAttachmentKeys } from "@/lib/query-keys";

export type PursuitAttachment = PursuitAttachmentOut;
export type PursuitAttachmentList = PursuitAttachmentListResponse;

export { pursuitAttachmentKeys } from "@/lib/query-keys";

function conOrganizacion(url: string, organizationId: number | null): string {
  if (organizationId == null) return url;
  const separador = url.includes("?") ? "&" : "?";
  return `${url}${separador}organization_id=${organizationId}`;
}

function baseUrl(pursuitId: number | string): string {
  return `/api/v1/pursuits/${encodeURIComponent(String(pursuitId))}/attachments`;
}

/**
 * Listado y límites. `organizationId === null` no desactiva la query: el
 * backend resuelve la organización personal cuando se omite, igual que en
 * `usePursuit`.
 */
export function usePursuitAttachments(
  pursuitId: number | string | null,
  options: { enabled?: boolean } = {},
) {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: [...pursuitAttachmentKeys.list(pursuitId ?? ""), organizationId],
    queryFn: () =>
      fetchWithAuth<PursuitAttachmentList>(conOrganizacion(baseUrl(pursuitId!), organizationId)),
    enabled: pursuitId != null && (options.enabled ?? true),
    staleTime: 30_000,
  });
}

export function useSubirAdjunto(pursuitId: number | string) {
  const queryClient = useQueryClient();
  const organizationId = useActiveOrganizationId();
  return useMutation({
    mutationFn: (fichero: File) =>
      fetchWithAuth<PursuitAttachment>(
        conOrganizacion(
          `${baseUrl(pursuitId)}?filename=${encodeURIComponent(fichero.name)}`,
          organizationId,
        ),
        {
          method: "POST",
          // El tipo del fichero manda: es lo que la API compara contra su
          // allowlist. `fetchWithAuth` pone `application/json` por defecto y
          // aquí eso daría un 415 sobre un PDF perfectamente válido.
          headers: { "Content-Type": fichero.type || "application/octet-stream" },
          body: fichero,
        },
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: pursuitAttachmentKeys.list(pursuitId) }),
  });
}

export function useBorrarAdjunto(pursuitId: number | string) {
  const queryClient = useQueryClient();
  const organizationId = useActiveOrganizationId();
  return useMutation({
    mutationFn: (attachmentId: number) =>
      fetchWithAuth<void>(
        conOrganizacion(`/api/v1/pursuits/attachments/${attachmentId}`, organizationId),
        { method: "DELETE" },
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: pursuitAttachmentKeys.list(pursuitId) }),
  });
}

export function useAdjuntoIndexable(pursuitId: number | string) {
  const queryClient = useQueryClient();
  const organizationId = useActiveOrganizationId();
  return useMutation({
    mutationFn: ({ attachmentId, indexable }: { attachmentId: number; indexable: boolean }) =>
      fetchWithAuth<PursuitAttachment>(
        conOrganizacion(
          `/api/v1/pursuits/attachments/${attachmentId}/indexable`,
          organizationId,
        ),
        { method: "PUT", body: JSON.stringify({ indexable }) },
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: pursuitAttachmentKeys.list(pursuitId) }),
  });
}

/**
 * Pide el enlace firmado y lo abre.
 *
 * Se pide en el momento de pulsar y no al listar: un enlace vive quince minutos
 * y emitir uno por fila al pintar la tabla repartiría credenciales de descarga
 * para ficheros que nadie va a abrir.
 */
export function useDescargarAdjunto(pursuitId: number | string) {
  const organizationId = useActiveOrganizationId();
  return useMutation({
    mutationFn: (attachmentId: number) =>
      fetchWithAuth<PursuitAttachmentDownloadLink>(
        conOrganizacion(
          `${baseUrl(pursuitId)}/${attachmentId}/enlace`,
          organizationId,
        ),
        { method: "POST" },
      ),
  });
}
