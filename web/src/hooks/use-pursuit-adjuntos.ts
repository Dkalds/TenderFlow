"use client";

/**
 * Adjuntos propios de una oportunidad (C6.3): la propuesta y los anexos que el
 * equipo escribe para responder al pliego.
 *
 * `GET|POST /pursuits/{id}/adjuntos`, `GET /pursuits/adjuntos/{id}/enlace` y
 * `DELETE /pursuits/adjuntos/{id}`, más `GET /pursuits/adjuntos/politica`, que
 * dice antes de subir si el entorno tiene almacén, el tope y los tipos.
 *
 * Tres decisiones que vienen del servidor y que aquí solo se respetan:
 *
 * - **La subida es cuerpo crudo**, no `multipart`: el fichero va como cuerpo y
 *   su nombre en `X-Filename`, codificado como URI (`lib/adjuntos.ts`).
 * - **La descarga va por enlace firmado**: primero `…/enlace` con la sesión
 *   delante, después el binario. El enlace ya lleva su query firmada (`exp`,
 *   `t`); la organización **se añade** a ella, no la sustituye.
 * - **La organización viaja siempre**, como en las tareas: sin ella el backend
 *   resolvería la personal, que no es la de la oportunidad que se mira.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiMutate, fetchBlobWithAuth, fetchWithAuth } from "@/lib/api-client";
import { organizacionResuelta, useActiveOrganizationId, type OrganizacionActiva } from "@/hooks/use-organization";
import { nombreParaCabecera, type Adjunto } from "@/lib/adjuntos";
import type { Schemas } from "@/lib/api-types";
import { guardarFichero } from "@/lib/export";
import { pursuitKeys } from "@/lib/query-keys";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";

type EnlaceAdjunto = Schemas["PursuitAttachmentLink"];

function conOrganizacion(organizationId: OrganizacionActiva): string {
  return organizationId != null ? `?organization_id=${organizationId}` : "";
}

function rutaAdjuntos(pursuitId: number, organizationId: OrganizacionActiva): string {
  return `/api/v1/pursuits/${pursuitId}/adjuntos${conOrganizacion(organizationId)}`;
}

/** Si el entorno acepta adjuntos, el tope por fichero y los tipos admitidos. */
export function usePoliticaAdjuntos() {
  return useQuery({
    queryKey: pursuitKeys.adjuntosPolitica,
    queryFn: ({ signal }) => apiGet("/api/v1/pursuits/adjuntos/politica", { signal }),
    // Cambia con un despliegue, no mientras se trabaja.
    staleTime: 10 * 60_000,
    meta: META_ERROR_EN_LINEA,
  });
}

export function usePursuitAdjuntos(pursuitId: number) {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: [...pursuitKeys.adjuntos(pursuitId), organizationId],
    queryFn: ({ signal }) => fetchWithAuth<Adjunto[]>(rutaAdjuntos(pursuitId, organizationId), { signal }),
    enabled: organizacionResuelta(organizationId),
    staleTime: 30_000,
    meta: META_ERROR_EN_LINEA,
  });
}

/**
 * Sube un fichero. `contentType` lo pone quien llama a partir de la política
 * (`validarFichero`), no `File.type`: el servidor exige que tipo y extensión
 * concuerden, y el sistema operativo no siempre dice el tipo que toca.
 */
export function useSubirAdjunto(pursuitId: number) {
  const queryClient = useQueryClient();
  const organizationId = useActiveOrganizationId();
  return useMutation({
    meta: { errorTitle: "No se pudo subir el adjunto" },
    mutationFn: ({ fichero, contentType }: { fichero: File; contentType: string }) =>
      fetchWithAuth<Adjunto>(rutaAdjuntos(pursuitId, organizationId), {
        method: "POST",
        body: fichero,
        headers: { "Content-Type": contentType, "X-Filename": nombreParaCabecera(fichero.name) },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: pursuitKeys.adjuntos(pursuitId) }),
  });
}

/** Retira un adjunto de la oportunidad. El servidor conserva el binario (v131). */
export function useRetirarAdjunto(pursuitId: number) {
  const queryClient = useQueryClient();
  const organizationId = useActiveOrganizationId();
  return useMutation({
    meta: { errorTitle: "No se pudo retirar el adjunto" },
    mutationFn: (attachmentId: number) =>
      apiMutate<void>("DELETE", `/api/v1/pursuits/adjuntos/${attachmentId}${conOrganizacion(organizationId)}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: pursuitKeys.adjuntos(pursuitId) }),
  });
}

/**
 * Pide el enlace firmado, descarga el binario y lo entrega con su nombre.
 *
 * Por `fetch` y no con un ancla a la ruta firmada: así un enlace caducado o un
 * adjunto ya retirado llega como `ApiError` que la pantalla puede explicar, en
 * vez de como una descarga fallida en el gestor del navegador.
 */
export function useDescargarAdjunto() {
  const organizationId = useActiveOrganizationId();
  return useMutation({
    meta: { errorTitle: "No se pudo descargar el adjunto" },
    mutationFn: async (adjunto: Adjunto) => {
      const enlace = await fetchWithAuth<EnlaceAdjunto>(
        `/api/v1/pursuits/adjuntos/${adjunto.id}/enlace${conOrganizacion(organizationId)}`,
      );
      const url = organizationId != null ? `${enlace.path}&organization_id=${organizationId}` : enlace.path;
      guardarFichero(adjunto.filename, await fetchBlobWithAuth(url));
    },
  });
}
