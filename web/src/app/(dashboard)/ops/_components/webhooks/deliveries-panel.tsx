"use client";

/**
 * Historial de entregas de un webhook: el único sitio donde se ve si la
 * integración está entregando de verdad o lleva días devolviendo 500.
 *
 * Desde la vista del equipo (`editable`), una entrega que agotó sus reintentos
 * (`failed`) se puede reenviar: la API la deja en cola y el job de reintentos
 * la manda con el mismo cuerpo y la misma firma que la primera vez. Las de
 * prueba no pasan por esa cola (no guardan el cuerpo), y por eso no ofrecen el
 * botón.
 */

import { RotateCcw } from "lucide-react";
import { PanelEmpty, PanelError } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { CABECERA_COLUMNA } from "@/components/ui/table";
import { useRedeliverWebhook, useWebhookDeliveries, type WebhookDelivery } from "@/hooks/use-webhooks";
import { cn } from "@/lib/utils";
import { formatDate } from "./formato";

function Resultado({ delivery }: { delivery: WebhookDelivery }) {
  // `pending` es una entrega en cola de reintento: su último intento falló,
  // pero todavía no está perdida, y pintarla como «Fallo» invita a reenviarla.
  if (delivery.estado === "pending") {
    return (
      <Badge variant="warning" size="sm">
        En cola
        {delivery.status_code != null && delivery.status_code !== 0 && ` · ${delivery.status_code}`}
      </Badge>
    );
  }
  return (
    <Badge variant={delivery.success ? "success" : "destructive"} size="sm">
      {delivery.success ? "OK" : "Fallo"}
      {delivery.status_code != null && ` · ${delivery.status_code}`}
    </Badge>
  );
}

export function DeliveriesPanel({
  webhookId,
  organizationId = null,
  editable = false,
}: {
  webhookId: number;
  /** Organización del webhook: las rutas por id la buscan en la query. */
  organizationId?: number | null;
  /** Solo la vista del equipo reenvía; la global de `/ops` es de lectura. */
  editable?: boolean;
}) {
  const { data, isPending, error, refetch } = useWebhookDeliveries(webhookId, organizationId);
  const reenviar = useRedeliverWebhook(webhookId, organizationId);

  if (isPending) return <Skeleton className="h-20 w-full" />;
  // Sin esto, un fallo al leer el historial se pintaba como «sin entregas»:
  // justo la lectura contraria a la que esta tabla existe para dar.
  if (error) {
    return (
      <PanelError
        variant="inline"
        title="No se pudo cargar el historial de entregas"
        error={error}
        onRetry={() => void refetch()}
      />
    );
  }
  if (!data?.length) {
    return (
      <PanelEmpty
        size="sm"
        title="Sin entregas todavía"
        hint="Aparecerán aquí cuando llegue el primer evento o cuando envíes una entrega de prueba."
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-tf-meta">
        <thead className="border-b border-border/60">
          <tr>
            <th scope="col" className={cn("px-3 py-2 text-left", CABECERA_COLUMNA)}>
              Evento
            </th>
            <th scope="col" className={cn("px-3 py-2 text-left", CABECERA_COLUMNA)}>
              Resultado
            </th>
            <th scope="col" className={cn("px-3 py-2 text-left", CABECERA_COLUMNA)}>
              Cuándo
            </th>
            {editable && (
              <th scope="col" className={cn("px-3 py-2 text-right", CABECERA_COLUMNA)}>
                <span className="sr-only">Acciones</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {data.map((delivery) => (
            <tr key={delivery.id} className="border-b border-border/40 last:border-0">
              <td className="px-3 py-2 font-mono">{delivery.event_type}</td>
              <td className="px-3 py-2">
                <Resultado delivery={delivery} />
              </td>
              <td className="text-muted-foreground px-3 py-2">{formatDate(delivery.created_at)}</td>
              {editable && (
                <td className="px-3 py-2 text-right">
                  {delivery.estado === "failed" && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={reenviar.isPending && reenviar.variables === delivery.id}
                      onClick={() => reenviar.mutate(delivery.id)}
                      aria-label={`Reenviar la entrega ${delivery.event_type} del ${formatDate(delivery.created_at)}`}
                    >
                      <RotateCcw aria-hidden="true" />
                      Reenviar
                    </Button>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
