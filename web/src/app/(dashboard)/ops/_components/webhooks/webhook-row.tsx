"use client";

/**
 * Ficha de un webhook: a qué eventos escucha, en qué formato entrega, cómo le
 * está yendo y —si el ámbito lo permite— las tres acciones sobre él.
 *
 * `editable` es lo que separa la vista de equipo de la global: la de `/ops` ve
 * todas las filas pero no toca ninguna (ver el docstring de `webhooks-view`).
 */

import * as React from "react";
import { Send, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { useDeleteWebhook, usePingWebhook, useUpdateWebhook } from "@/hooks/use-webhooks";
import type { WebhookAmpliado } from "../../_hooks/use-webhooks-ambito";
import { DeliveriesPanel } from "./deliveries-panel";
import { FORMATO_LABEL, formatDate } from "./formato";

export function WebhookRow({ webhook, editable }: { webhook: WebhookAmpliado; editable: boolean }) {
  const [open, setOpen] = React.useState(false);
  const update = useUpdateWebhook();
  const remove = useDeleteWebhook();
  const ping = usePingWebhook();
  const formato = webhook.formato ?? "json";

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 pb-3">
        <div className="min-w-0">
          <CardTitle className="text-sm">{webhook.name}</CardTitle>
          <p className="text-muted-foreground mt-1 truncate font-mono text-xs">{webhook.url}</p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Badge variant="outline" className="text-[10px]">
              {FORMATO_LABEL[formato] ?? formato}
            </Badge>
            {(webhook.event_types ?? []).map((event) => (
              <Badge key={event} variant="secondary" className="font-mono text-[10px]">
                {event}
              </Badge>
            ))}
            {/* Un webhook sin organización es anterior a `v108`: entrega igual,
                pero no lo ve ningún equipo. Etiquetarlo evita que alguien lo dé
                por perdido y cree un duplicado. */}
            {webhook.organization_id == null && (
              <Badge variant="outline" className="text-[10px]">
                sin organización
              </Badge>
            )}
            {/* El backend cuenta los fallos consecutivos; si son visibles, el
                usuario puede actuar antes de que el webhook se desactive. */}
            {(webhook.failure_count ?? 0) > 0 && (
              <Badge variant="destructive" className="text-[10px]">
                {webhook.failure_count} fallo(s) seguidos
              </Badge>
            )}
          </div>
          <p className="text-muted-foreground mt-2 text-[11px]">
            Última entrega: {formatDate(webhook.last_triggered_at)}
            {webhook.last_status != null && ` · HTTP ${webhook.last_status}`}
          </p>
        </div>
        {editable && (
          <div className="flex flex-none items-center gap-2">
            <Switch
              checked={webhook.active ?? false}
              onCheckedChange={(active) => update.mutate({ id: webhook.id, active })}
              aria-label={`${webhook.active ? "Desactivar" : "Activar"} ${webhook.name}`}
            />
            <Button
              size="sm"
              variant="outline"
              onClick={() => ping.mutate(webhook.id)}
              disabled={ping.isPending}
              aria-label={`Enviar entrega de prueba a ${webhook.name}`}
            >
              <Send className="h-3.5 w-3.5" aria-hidden="true" />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                // Confirmación explícita: borrar un webhook rompe una integración
                // viva del cliente y no se puede deshacer.
                if (window.confirm(`¿Eliminar el webhook «${webhook.name}»?`)) {
                  remove.mutate(webhook.id);
                }
              }}
              aria-label={`Eliminar ${webhook.name}`}
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
            </Button>
          </div>
        )}
      </CardHeader>
      <CardContent className="pt-0">
        <Button size="sm" variant="ghost" onClick={() => setOpen((v) => !v)}>
          {open ? "Ocultar entregas" : "Ver entregas"}
        </Button>
        {open && <DeliveriesPanel webhookId={webhook.id} />}
      </CardContent>
    </Card>
  );
}
