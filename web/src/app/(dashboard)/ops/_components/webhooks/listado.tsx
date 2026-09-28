"use client";

/**
 * Los tres estados del listado —error, cargando y vacío— compartidos por las
 * dos vistas. El texto del vacío lo pone cada una: el equipo puede crear uno y
 * la vista global no, así que sugerirle lo mismo a los dos sería mentirle a uno.
 */

import { PanelEmpty, PanelError } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import type { WebhookAmpliado } from "../../_hooks/use-webhooks-ambito";
import { WebhookRow } from "./webhook-row";

export function Listado({
  webhooks,
  isPending,
  error,
  onRetry,
  editable,
  vacio,
}: {
  webhooks: WebhookAmpliado[] | undefined;
  isPending: boolean;
  error: unknown;
  onRetry?: () => void;
  editable: boolean;
  vacio: string;
}) {
  return (
    <>
      {error != null && (
        <PanelError title="No se pudieron cargar los webhooks" error={error} onRetry={onRetry} />
      )}

      {isPending && <Skeleton className="h-24 w-full rounded-xl" />}

      {!isPending && error == null && !webhooks?.length && <PanelEmpty title="Sin webhooks" hint={vacio} />}

      <div className="space-y-3">
        {webhooks?.map((webhook) => (
          <WebhookRow key={webhook.id} webhook={webhook} editable={editable} />
        ))}
      </div>
    </>
  );
}
