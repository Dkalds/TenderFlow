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
import { apiGet, apiMutate, fetchWithAuth } from "@/lib/api-client";
import type {
  WebhookCreate,
  WebhookCreateResponse,
  WebhookDelivery,
  WebhookOut,
  WebhookPingResult,
  WebhookUpdate,
} from "@/lib/api-types";
import { webhookKeys } from "@/lib/query-keys";

export type { WebhookCreateResponse, WebhookDelivery, WebhookOut, WebhookPingResult };

const WEBHOOKS_KEY = webhookKeys.all;

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

export function useWebhookDeliveries(webhookId: number | null) {
  return useQuery({
    queryKey: webhookKeys.deliveries(webhookId),
    queryFn: () => fetchWithAuth<WebhookDelivery[]>(`/api/v1/webhooks/${webhookId}/deliveries`),
    enabled: webhookId !== null,
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
    onError: () => toast.error("No se pudo crear el webhook"),
  });
}

export function useUpdateWebhook() {
  const qc = useQueryClient();
  return useMutation<WebhookOut, unknown, WebhookUpdateInput>({
    mutationFn: ({ id, ...patch }) => apiMutate<WebhookOut>("PATCH", `/api/v1/webhooks/${id}`, patch),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: WEBHOOKS_KEY });
    },
    onError: () => toast.error("No se pudo actualizar el webhook"),
  });
}

export function useDeleteWebhook() {
  const qc = useQueryClient();
  return useMutation<void, unknown, number>({
    mutationFn: (id) => apiMutate<void>("DELETE", `/api/v1/webhooks/${id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: WEBHOOKS_KEY });
      toast.success("Webhook eliminado");
    },
    onError: () => toast.error("No se pudo eliminar el webhook"),
  });
}

/** Entrega de prueba. Devuelve el resultado real, incluido el fallo. */
export function usePingWebhook() {
  const qc = useQueryClient();
  return useMutation<WebhookPingResult, unknown, number>({
    mutationFn: (id) => apiMutate<WebhookPingResult>("POST", `/api/v1/webhooks/${id}/ping`),
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
    onError: () => toast.error("No se pudo enviar la entrega de prueba"),
  });
}
