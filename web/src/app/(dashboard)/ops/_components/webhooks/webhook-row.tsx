"use client";

/**
 * Ficha de un webhook: a qué eventos escucha, en qué formato entrega, cómo le
 * está yendo y —si el ámbito lo permite— las acciones sobre él: activarlo,
 * probarlo, rotar su secreto y eliminarlo.
 *
 * `editable` es lo que separa la vista de equipo de la global: la de `/ops` ve
 * todas las filas pero no toca ninguna (ver el docstring de `webhooks-view`).
 *
 * Rotar y eliminar piden confirmación en la propia ficha, y solo una a la vez:
 * las dos rompen la integración del receptor hasta que alguien actúe en él.
 * El secreto rotado se enseña una vez, con el mismo aviso que el del alta.
 */

import * as React from "react";
import { ChevronDown, ChevronUp, KeyRound, Send, Trash2 } from "lucide-react";
import { Panel } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  useDeleteWebhook,
  usePingWebhook,
  useRotateWebhookSecret,
  useUpdateWebhook,
} from "@/hooks/use-webhooks";
import type { WebhookAmpliado } from "../../_hooks/use-webhooks-ambito";
import { DeliveriesPanel } from "./deliveries-panel";
import { FORMATO_LABEL, formatDate } from "./formato";
import { SecretNotice } from "./secret-notice";

type Confirmacion = "eliminar" | "rotar";

export function WebhookRow({ webhook, editable }: { webhook: WebhookAmpliado; editable: boolean }) {
  const [open, setOpen] = React.useState(false);
  // La organización del webhook viaja en cada petición: sin ella la API busca
  // en la personal y, desde un equipo, todo acababa en 404.
  const organizationId = webhook.organization_id ?? null;
  const update = useUpdateWebhook(organizationId);
  const remove = useDeleteWebhook(organizationId);
  const ping = usePingWebhook(organizationId);
  const rotar = useRotateWebhookSecret(organizationId);
  const [secretoRotado, setSecretoRotado] = React.useState<string | null>(null);
  const formato = webhook.formato ?? "json";
  const fallos = webhook.failure_count ?? 0;
  const idEntregas = `entregas-webhook-${webhook.id}`;
  const [confirmando, setConfirmando] = React.useState<Confirmacion | null>(null);
  const botonEliminar = React.useRef<HTMLButtonElement>(null);
  const botonRotar = React.useRef<HTMLButtonElement>(null);
  const botonCancelar = React.useRef<HTMLButtonElement>(null);
  const estabaConfirmando = React.useRef<Confirmacion | null>(null);
  const cancelar = () => setConfirmando(null);

  // Al armar la confirmación el foco pasa a «Cancelar» (lo seguro con el
  // teclado); al desarmarla vuelve al botón del que salió.
  React.useEffect(() => {
    if (confirmando) botonCancelar.current?.focus();
    else if (estabaConfirmando.current === "eliminar") botonEliminar.current?.focus();
    else if (estabaConfirmando.current === "rotar") botonRotar.current?.focus();
    estabaConfirmando.current = confirmando;
  }, [confirmando]);

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
                  ref={botonRotar}
                  size="icon-sm"
                  variant="outline"
                  onClick={() => setConfirmando("rotar")}
                  disabled={confirmando != null || rotar.isPending}
                  aria-label={`Rotar el secreto de ${webhook.name}`}
                >
                  <KeyRound aria-hidden="true" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Rotar el secreto de firma</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  ref={botonEliminar}
                  size="icon-sm"
                  variant="ghost"
                  className="text-destructive"
                  onClick={() => setConfirmando("eliminar")}
                  disabled={confirmando != null || remove.isPending}
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
      {/* Confirmación en dos pasos dentro de la propia ficha, como en el resto
          de la consola: borrar un webhook rompe una integración viva del
          cliente y no se puede deshacer. */}
      {editable && confirmando === "eliminar" && (
        <div
          role="group"
          aria-label={`Confirmar la eliminación de ${webhook.name}`}
          className="mt-3 flex flex-wrap items-center gap-2 text-tf-meta"
        >
          <span className="text-muted-foreground">
            ¿Eliminar el webhook «{webhook.name}»? Dejará de recibir entregas y no se puede deshacer.
          </span>
          <Button
            size="sm"
            variant="destructive"
            disabled={remove.isPending}
            onClick={() => remove.mutate(webhook.id, { onSettled: () => setConfirmando(null) })}
          >
            Sí, eliminar
          </Button>
          <Button ref={botonCancelar} size="sm" variant="ghost" onClick={cancelar}>
            Cancelar
          </Button>
        </div>
      )}
      {editable && confirmando === "rotar" && (
        <div
          role="group"
          aria-label={`Confirmar la rotación del secreto de ${webhook.name}`}
          className="mt-3 flex flex-wrap items-center gap-2 text-tf-meta"
        >
          <span className="text-muted-foreground">
            ¿Rotar el secreto de «{webhook.name}»? El actual deja de firmar en el acto: carga el nuevo en el
            receptor antes de la próxima entrega, o desactiva el webhook mientras tanto.
          </span>
          <Button
            size="sm"
            disabled={rotar.isPending}
            onClick={() =>
              rotar.mutate(webhook.id, {
                onSuccess: (rotado) => setSecretoRotado(rotado.secret),
                onSettled: () => setConfirmando(null),
              })
            }
          >
            Sí, rotar
          </Button>
          <Button ref={botonCancelar} size="sm" variant="ghost" onClick={cancelar}>
            Cancelar
          </Button>
        </div>
      )}
      {secretoRotado && (
        <div className="mt-3">
          <SecretNotice secret={secretoRotado} onDismiss={() => setSecretoRotado(null)}>
            El secreto anterior ya no firma: las entregas que salgan desde ahora llevan este.
          </SecretNotice>
        </div>
      )}
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
          <DeliveriesPanel webhookId={webhook.id} organizationId={organizationId} editable={editable} />
        </div>
      )}
    </Panel>
  );
}
