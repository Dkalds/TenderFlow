"use client";

/**
 * Historial de entregas de un webhook: el único sitio donde se ve si la
 * integración está entregando de verdad o lleva días devolviendo 500.
 */

import { PanelEmpty, PanelError } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { CABECERA_COLUMNA } from "@/components/ui/table";
import { useWebhookDeliveries } from "@/hooks/use-webhooks";
import { cn } from "@/lib/utils";
import { formatDate } from "./formato";

export function DeliveriesPanel({ webhookId }: { webhookId: number }) {
  const { data, isPending, error, refetch } = useWebhookDeliveries(webhookId);

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
          </tr>
        </thead>
        <tbody>
          {data.map((delivery) => (
            <tr key={delivery.id} className="border-b border-border/40 last:border-0">
              <td className="px-3 py-2 font-mono">{delivery.event_type}</td>
              <td className="px-3 py-2">
                <Badge variant={delivery.success ? "success" : "destructive"} size="sm">
                  {delivery.success ? "OK" : "Fallo"}
                  {delivery.status_code != null && ` · ${delivery.status_code}`}
                </Badge>
              </td>
              <td className="text-muted-foreground px-3 py-2">{formatDate(delivery.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
