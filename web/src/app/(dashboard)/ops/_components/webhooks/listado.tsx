"use client";

/**
 * Los tres estados del listado —error, cargando y vacío— compartidos por las
 * dos vistas. El texto del vacío lo pone cada una: el equipo puede crear uno y
 * la vista global no, así que sugerirle lo mismo a los dos sería mentirle a uno.
 */

import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import type { WebhookAmpliado } from "../../_hooks/use-webhooks-ambito";
import { WebhookRow } from "./webhook-row";

export function Listado({
  webhooks,
  isPending,
  error,
  editable,
  vacio,
}: {
  webhooks: WebhookAmpliado[] | undefined;
  isPending: boolean;
  error: unknown;
  editable: boolean;
  vacio: string;
}) {
  return (
    <>
      {error != null && (
        <div role="alert" className="text-destructive text-sm">
          No se pudieron cargar los webhooks.
        </div>
      )}

      {isPending && <Skeleton className="h-24 w-full" />}

      {!isPending && error == null && !webhooks?.length && (
        <EmptyState title="Sin webhooks" hint={vacio} />
      )}

      <div className="space-y-3">
        {webhooks?.map((webhook) => (
          <WebhookRow key={webhook.id} webhook={webhook} editable={editable} />
        ))}
      </div>
    </>
  );
}
