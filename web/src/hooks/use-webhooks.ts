/**
 * Webhooks — entrega HMAC de eventos a sistemas externos.
 *
 * El backend estaba completo (firma HMAC, reintentos, DNS-pinning, historial
 * de entregas) pero no había ninguna superficie de usuario: usarlo exigía
 * llamar a la API a mano. Estos hooks son su cliente.
 *
 * Todos los tipos se derivan del esquema generado (`lib/api-types.ts`): un
 * campo que la API no envía deja de compilar aquí en vez de aparecer como
 * `undefined` en pantalla.
 */
"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError, apiGet, apiMutate, fetchWithAuth } from "@/lib/api-client";
import type {
  Schemas,
  WebhookCreate,
  WebhookCreateResponse,
  WebhookDelivery,
  WebhookOut,
  WebhookPingResult,
  WebhookUpdate,
} from "@/lib/api-types";
import { webhookKeys } from "@/lib/query-keys";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";

export type { WebhookCreateResponse, WebhookDelivery, WebhookOut, WebhookPingResult };
export type WebhookSecretRotated = Schemas["WebhookSecretRotated"];

const WEBHOOKS_KEY = webhookKeys.all;

/**
 * La organización del webhook en la query (`?organization_id=`).
 *
 * Todas las rutas por id resuelven el ámbito con `require_organization`, que
 * sin el parámetro mira la organización **personal**. Las mutaciones de la
 * ficha no lo mandaban, así que desde /equipo, con un equipo activo, activar,
 * probar o borrar un webhook del equipo daba 404. La fila sabe de qué
 * organización es su webhook; es lo que se pasa aquí.
 */
function conOrganizacion(ruta: string, organizationId: number | null | undefined): string {
  return organizationId == null ? ruta : `${ruta}?organization_id=${organizationId}`;
}

/** Cuerpo del alta, tal y como lo declara la API. */
export type WebhookCreateInput = WebhookCreate;

/** Cuerpo de la edición; el `id` va en la ruta, no en el body. */
export type WebhookUpdateInput = WebhookUpdate & { id: number };

/**
 * `GET /webhooks` es la única ruta de webhooks sin DTO: el backend la anota
 * `-> list[dict[str, Any]]` (su hermana `GET /webhooks/{id}` sí devuelve
 * `WebhookOut`), así que el esquema generado la describe como una lista de
 * objetos opacos. Pasarla por `apiGet` cambiaría `WebhookOut[]` por
 * `{ [k: string]: unknown }[]` y rompería a quien la pinta, de modo que se
 * queda en `fetchWithAuth` hasta que la ruta declare su modelo. El tipo de
 * abajo es, hasta entonces, una suposición del frontend.
 */
export function useWebhooks() {
  return useQuery({
    queryKey: WEBHOOKS_KEY,
    queryFn: () => fetchWithAuth<WebhookOut[]>("/api/v1/webhooks"),
    meta: META_ERROR_EN_LINEA,
  });
}

/** Tipos de evento válidos, servidos por el backend (la UI no los duplica). */
export function useWebhookEventTypes() {
  return useQuery({
    queryKey: webhookKeys.eventTypes,
    queryFn: () =>
      apiGet("/api/v1/webhooks/event-types").then((response) => response.event_types),
    staleTime: 60 * 60_000,
  });
}

export function useWebhookDeliveries(webhookId: number | null, organizationId?: number | null) {
  return useQuery({
    queryKey: webhookKeys.deliveries(webhookId),
    queryFn: () =>
      fetchWithAuth<WebhookDelivery[]>(conOrganizacion(`/api/v1/webhooks/${webhookId}/deliveries`, organizationId)),
    enabled: webhookId !== null,
    meta: META_ERROR_EN_LINEA,
  });
}

/**
 * Alta de webhook. La respuesta trae el `secret` **una sola vez**: no hay
 * endpoint que lo vuelva a exponer, así que quien consuma este hook tiene que
 * enseñarlo en ese momento o se pierde.
 */
export function useCreateWebhook() {
  const qc = useQueryClient();
  return useMutation<WebhookCreateResponse, unknown, WebhookCreateInput>({
    mutationFn: (input) => apiMutate<WebhookCreateResponse>("POST", "/api/v1/webhooks", input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: WEBHOOKS_KEY });
    },
    meta: { errorTitle: "No se pudo crear el webhook" },
  });
}

export function useUpdateWebhook(organizationId?: number | null) {
  const qc = useQueryClient();
  return useMutation<WebhookOut, unknown, WebhookUpdateInput>({
    mutationFn: ({ id, ...patch }) =>
      apiMutate<WebhookOut>("PATCH", conOrganizacion(`/api/v1/webhooks/${id}`, organizationId), patch),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: WEBHOOKS_KEY });
    },
    meta: { errorTitle: "No se pudo actualizar el webhook" },
  });
}

export function useDeleteWebhook(organizationId?: number | null) {
  const qc = useQueryClient();
  return useMutation<void, unknown, number>({
    mutationFn: (id) => apiMutate<void>("DELETE", conOrganizacion(`/api/v1/webhooks/${id}`, organizationId)),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: WEBHOOKS_KEY });
      toast.success("Webhook eliminado");
    },
    meta: { errorTitle: "No se pudo eliminar el webhook" },
  });
}

/** Entrega de prueba. Devuelve el resultado real, incluido el fallo. */
export function usePingWebhook(organizationId?: number | null) {
  const qc = useQueryClient();
  return useMutation<WebhookPingResult, unknown, number>({
    mutationFn: (id) =>
      apiMutate<WebhookPingResult>("POST", conOrganizacion(`/api/v1/webhooks/${id}/ping`, organizationId)),
    onSuccess: (result) => {
      void qc.invalidateQueries({ queryKey: WEBHOOKS_KEY });
      if (result.success) {
        toast.success(`Entrega correcta (HTTP ${result.status_code ?? "?"})`);
      } else {
        // Un ping fallido no es un error de la app: es el resultado que el
        // usuario vino a comprobar, y su motivo es la información útil.
        toast.warning(`La entrega falló tras ${result.attempts ?? 1} intento(s): ${result.error ?? "sin detalle"}`);
      }
    },
    meta: { errorTitle: "No se pudo enviar la entrega de prueba" },
  });
}

/**
 * Secret nuevo para un webhook (`POST /webhooks/{id}/rotate-secret`).
 *
 * Como en el alta, la respuesta trae el secret **una sola vez** y quien llama
 * tiene que enseñarlo en ese momento. El anterior deja de firmar en el acto:
 * no hay periodo de gracia, por eso la ficha pide confirmación antes.
 */
export function useRotateWebhookSecret(organizationId?: number | null) {
  const qc = useQueryClient();
  return useMutation<WebhookSecretRotated, unknown, number>({
    mutationFn: (id) =>
      apiMutate<WebhookSecretRotated>(
        "POST",
        conOrganizacion(`/api/v1/webhooks/${id}/rotate-secret`, organizationId),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: WEBHOOKS_KEY });
    },
    meta: { errorTitle: "No se pudo rotar el secreto" },
  });
}

/**
 * Reencola una entrega fallida (`POST …/deliveries/{id}/redeliver`, C2.4).
 *
 * La API responde 202: no reenvía en la petición, la marca para que el job de
 * reintentos la recoja. Por eso el aviso dice «en cola» y no «entregada», y el
 * historial se vuelve a pedir para que la fila lo refleje.
 */
export function useRedeliverWebhook(webhookId: number, organizationId?: number | null) {
  const qc = useQueryClient();
  return useMutation<unknown, unknown, number>({
    mutationFn: (deliveryId) =>
      apiMutate<unknown>(
        "POST",
        conOrganizacion(`/api/v1/webhooks/${webhookId}/deliveries/${deliveryId}/redeliver`, organizationId),
      ),
    onSuccess: () => {
      toast.success("Entrega en cola: se reenviará en el próximo ciclo de reintentos");
    },
    meta: {
      errorTitle: "No se pudo reenviar la entrega",
      errorDescription: (error: unknown) =>
        error instanceof ApiError && error.status === 409
          ? "Esa entrega ya se completó o no se puede reenviar"
          : undefined,
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: webhookKeys.deliveries(webhookId) });
    },
  });
}
