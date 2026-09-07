"use client";

/**
 * Historial de entregas de un webhook: el único sitio donde se ve si la
 * integración está entregando de verdad o lleva días devolviendo 500.
 */

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useWebhookDeliveries } from "@/hooks/use-webhooks";
import { formatDate } from "./formato";

export function DeliveriesPanel({ webhookId }: { webhookId: number }) {
  const { data, isPending } = useWebhookDeliveries(webhookId);

  if (isPending) return <Skeleton className="h-20 w-full" />;
  if (!data?.length) {
    return <p className="text-muted-foreground px-3 py-4 text-xs">Sin entregas registradas todavía.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-muted-foreground border-b">
          <tr>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              Evento
            </th>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              Resultado
            </th>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              Cuándo
            </th>
          </tr>
        </thead>
        <tbody>
          {data.map((delivery) => (
            <tr key={delivery.id} className="border-b last:border-0">
              <td className="px-3 py-2 font-mono">{delivery.event_type}</td>
              <td className="px-3 py-2">
                <Badge variant={delivery.success ? "default" : "destructive"}>
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
