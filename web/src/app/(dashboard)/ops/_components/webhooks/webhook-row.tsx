"use client";

/**
 * Ficha de un webhook: a qué eventos escucha, en qué formato entrega, cómo le
 * está yendo y —si el ámbito lo permite— las tres acciones sobre él.
 *
 * `editable` es lo que separa la vista de equipo de la global: la de `/ops` ve
 * todas las filas pero no toca ninguna (ver el docstring de `webhooks-view`).
 */

import * as React from "react";
import { ChevronDown, ChevronUp, Send, Trash2 } from "lucide-react";
import { Panel } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
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
  const fallos = webhook.failure_count ?? 0;
  const idEntregas = `entregas-webhook-${webhook.id}`;

  return (
    <Panel>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-tf-body font-semibold">{webhook.name}</h3>
          <p className="text-muted-foreground mt-1 truncate font-mono text-tf-meta">{webhook.url}</p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Badge variant="outline" size="sm">
              {FORMATO_LABEL[formato] ?? formato}
            </Badge>
            {(webhook.event_types ?? []).map((event) => (
              <Badge key={event} variant="secondary" size="sm" className="font-mono">
                {event}
              </Badge>
            ))}
            {/* Un webhook sin organización es anterior a `v108`: entrega igual,
                pero no lo ve ningún equipo. Etiquetarlo evita que alguien lo dé
                por perdido y cree un duplicado. */}
            {webhook.organization_id == null && (
              <Badge variant="outline" size="sm">
                Sin organización
              </Badge>
            )}
            {/* El backend cuenta los fallos consecutivos; si son visibles, el
                usuario puede actuar antes de que el webhook se desactive. */}
            {fallos > 0 && (
              <Badge variant="destructive" size="sm">
                {fallos} {fallos === 1 ? "fallo seguido" : "fallos seguidos"}
              </Badge>
            )}
          </div>
          <p className="text-muted-foreground mt-2 text-tf-meta">
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
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size="icon-sm"
                  variant="outline"
                  onClick={() => ping.mutate(webhook.id)}
                  disabled={ping.isPending}
                  aria-label={`Enviar entrega de prueba a ${webhook.name}`}
                >
                  <Send aria-hidden="true" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Enviar entrega de prueba</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  className="text-destructive"
                  onClick={() => {
                    // Confirmación explícita: borrar un webhook rompe una integración
                    // viva del cliente y no se puede deshacer.
                    if (window.confirm(`¿Eliminar el webhook «${webhook.name}»?`)) {
                      remove.mutate(webhook.id);
                    }
                  }}
                  aria-label={`Eliminar ${webhook.name}`}
                >
                  <Trash2 aria-hidden="true" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Eliminar webhook</TooltipContent>
            </Tooltip>
          </div>
        )}
      </div>
      <Button
        size="sm"
        variant="ghost"
        className="mt-2 -ml-2.5"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={open ? idEntregas : undefined}
      >
        {open ? "Ocultar entregas" : "Ver entregas"}
        {open ? <ChevronUp aria-hidden="true" /> : <ChevronDown aria-hidden="true" />}
      </Button>
      {open && (
        <div id={idEntregas}>
          <DeliveriesPanel webhookId={webhook.id} />
        </div>
      )}
    </Panel>
  );
}
