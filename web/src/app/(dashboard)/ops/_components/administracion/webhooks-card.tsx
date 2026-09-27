"use client";

/**
 * Webhooks — recurso compartido a nivel de instancia (F13·C3.1/C3.3a).
 *
 * Alta con secreto de un solo uso, listado con su estado y contador de fallos,
 * y las dos acciones por fila: entrega de prueba y borrado con confirmación.
 */

import { Plus, Radio, Trash2 } from "lucide-react";
import { Panel, PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ETIQUETA_CAMPO, Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { WebhookOut } from "@/hooks/use-webhooks";
import { useWebhookForm, WEBHOOK_EVENTS } from "../../_hooks/use-webhook-form";
import { SecretRevealCard } from "./secret-reveal-card";

type WebhookForm = ReturnType<typeof useWebhookForm>;

function WebhookRow({ wh, form }: { wh: WebhookOut; form: WebhookForm }) {
  const confirmando = form.confirmDeleteWebhookId === wh.id;
  const fallos = wh.failure_count ?? 0;

  return (
    <li className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border/60 p-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-tf-body font-medium">{wh.name}</p>
          <Badge variant={wh.active ? "success" : "secondary"} size="sm">
            {wh.active ? "Activo" : "Inactivo"}
          </Badge>
          {fallos > 0 && (
            <Badge variant="destructive" size="sm">
              {fallos} {fallos === 1 ? "fallo" : "fallos"}
            </Badge>
          )}
        </div>
        <p className="text-muted-foreground truncate font-mono text-tf-meta">{wh.url}</p>
        <div className="mt-1 flex flex-wrap gap-1">
          {wh.event_types.map((ev) => (
            <Badge key={ev} variant="outline" size="sm" className="font-mono">
              {ev}
            </Badge>
          ))}
        </div>
      </div>
      <div className="flex items-center gap-1">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              disabled={form.pingPendiente}
              onClick={() => form.ping(wh.id)}
              aria-label="Enviar entrega de prueba"
            >
              <Radio aria-hidden="true" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Enviar entrega de prueba</TooltipContent>
        </Tooltip>
        {confirmando && <span className="text-destructive text-tf-meta">¿Confirmar?</span>}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant={confirmando ? "destructive" : "ghost"}
              size="icon-sm"
              className={confirmando ? "" : "text-destructive"}
              disabled={form.borrando}
              onClick={() => form.pedirBorrado(wh.id)}
              aria-label={confirmando ? "Confirmar eliminación de webhook" : "Eliminar webhook"}
            >
              <Trash2 aria-hidden="true" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{confirmando ? "Confirmar eliminación" : "Eliminar webhook"}</TooltipContent>
        </Tooltip>
        {confirmando && (
          <Button variant="ghost" size="sm" onClick={form.cancelarBorrado}>
            Cancelar
          </Button>
        )}
      </div>
    </li>
  );
}

export function WebhooksCard() {
  const form = useWebhookForm();

  return (
    <Panel>
      <PanelTitle
        title="Webhooks"
        hint="Integraciones salientes de la instancia: todos los administradores ven y gestionan los mismos"
      />
      <div className="space-y-4">
        {form.newWebhookSecret && (
          <SecretRevealCard
            aviso="Secreto generado: cópialo ahora, no se volverá a mostrar."
            secret={form.newWebhookSecret}
            onClose={form.clearNewWebhookSecret}
          />
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Nombre" htmlFor="wh-name">
            <Input
              id="wh-name"
              placeholder="p. ej. slack-alertas"
              value={form.whName}
              onChange={(e) => form.setWhName(e.target.value)}
            />
          </Field>
          <Field label="URL" htmlFor="wh-url">
            <Input
              id="wh-url"
              placeholder="https://hooks.example.com/licitaciones"
              value={form.whUrl}
              onChange={(e) => form.setWhUrl(e.target.value)}
            />
          </Field>
        </div>
        <fieldset className="space-y-1.5">
          <legend className={ETIQUETA_CAMPO}>Eventos</legend>
          <div className="flex flex-wrap gap-4 pt-1.5">
            {WEBHOOK_EVENTS.map((ev) => (
              <label key={ev} className="flex items-center gap-1.5 font-mono text-tf-meta">
                <Checkbox
                  checked={form.whEvents.includes(ev)}
                  onCheckedChange={(checked) => form.toggleWhEvent(ev, checked === true)}
                />
                {ev}
              </label>
            ))}
          </div>
        </fieldset>
        <Button size="sm" onClick={form.crear} disabled={!form.whName.trim() || !form.whUrl.trim() || form.creando}>
          <Plus aria-hidden="true" />
          {form.creando ? "Creando…" : "Crear webhook"}
        </Button>

        <Separator />

        {form.isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-5 w-3/4" />
          </div>
        ) : form.error ? (
          <PanelError variant="inline" title="No se pudieron cargar los webhooks" error={form.error} />
        ) : !form.webhooks || form.webhooks.length === 0 ? (
          <PanelEmpty
            size="sm"
            title="No hay webhooks registrados"
            hint="Crea el primero con el formulario de arriba."
          />
        ) : (
          <ul className="space-y-2">
            {form.webhooks.map((wh) => (
              <WebhookRow key={wh.id} wh={wh} form={form} />
            ))}
          </ul>
        )}
      </div>
    </Panel>
  );
}
