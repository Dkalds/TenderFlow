"use client";

/**
 * Alta, borrado y prueba de webhooks desde Administración.
 *
 * Reusa los hooks de `@/hooks/use-webhooks`, que son los que ya usaba
 * `webhooks-view.tsx`. Antes había en la vista una copia completa —misma clave
 * `["webhooks"]`, mismas cuatro rutas, otros toasts— y las dos vistas se montan
 * en el mismo espacio `/ops`: dos `queryFn` distintas bajo una clave compartida,
 * decidida por cuál se montara primero.
 */

import { useState } from "react";
import {
  useCreateWebhook,
  useDeleteWebhook,
  usePingWebhook,
  useWebhooks,
} from "@/hooks/use-webhooks";

export const WEBHOOK_EVENTS = ["*", "watchlist_match", "watchlist_rule.matched", "daily_summary"];

export function useWebhookForm() {
  const [newWebhookSecret, setNewWebhookSecret] = useState<string | null>(null);
  const [whName, setWhName] = useState("");
  const [whUrl, setWhUrl] = useState("");
  const [whEvents, setWhEvents] = useState<string[]>(["*"]);
  const [confirmDeleteWebhookId, setConfirmDeleteWebhookId] = useState<number | null>(null);

  const { data: webhooks, isLoading, error } = useWebhooks();
  const createWebhook = useCreateWebhook();
  const deleteWebhook = useDeleteWebhook();
  const pingWebhook = usePingWebhook();

  function toggleWhEvent(event: string, checked: boolean) {
    setWhEvents((prev) => (checked ? [...prev, event] : prev.filter((e) => e !== event)));
  }

  function crear() {
    createWebhook.mutate(
      {
        name: whName,
        url: whUrl,
        event_types: whEvents.length > 0 ? whEvents : ["*"],
      },
      {
        onSuccess: (data) => {
          // El `secret` sólo viaja en esta respuesta: se enseña aquí o
          // se pierde (no hay endpoint que lo vuelva a exponer).
          setNewWebhookSecret(data.secret);
          setWhName("");
          setWhUrl("");
          setWhEvents(["*"]);
        },
      },
    );
  }

  function pedirBorrado(id: number) {
    if (confirmDeleteWebhookId !== id) {
      setConfirmDeleteWebhookId(id);
      return;
    }
    deleteWebhook.mutate(id, { onSettled: () => setConfirmDeleteWebhookId(null) });
  }

  return {
    webhooks,
    isLoading,
    error,
    newWebhookSecret,
    clearNewWebhookSecret: () => setNewWebhookSecret(null),
    whName,
    setWhName,
    whUrl,
    setWhUrl,
    whEvents,
    toggleWhEvent,
    crear,
    creando: createWebhook.isPending,
    confirmDeleteWebhookId,
    cancelarBorrado: () => setConfirmDeleteWebhookId(null),
    pedirBorrado,
    borrando: deleteWebhook.isPending,
    ping: (id: number) => pingWebhook.mutate(id),
    pingPendiente: pingWebhook.isPending,
  };
}
