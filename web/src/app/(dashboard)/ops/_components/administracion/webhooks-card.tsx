"use client";

/**
 * Webhooks — recurso compartido a nivel de instancia (F13·C3.1/C3.3a).
 *
 * Alta con secret de un solo uso, listado con su estado y contador de fallos, y
 * las dos acciones por fila: entrega de prueba y borrado con confirmación.
 */

import { Info, Plus, Radio, Trash2, Webhook as WebhookIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { WebhookOut } from "@/hooks/use-webhooks";
import { cn } from "@/lib/utils";
import { useWebhookForm, WEBHOOK_EVENTS } from "../../_hooks/use-webhook-form";
import { SecretRevealCard } from "./secret-reveal-card";

type WebhookForm = ReturnType<typeof useWebhookForm>;

function WebhookRow({ wh, form }: { wh: WebhookOut; form: WebhookForm }) {
  const confirmando = form.confirmDeleteWebhookId === wh.id;

  return (
    <div className="border-border/70 flex flex-wrap items-center justify-between gap-2 rounded-md border p-3">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="font-medium">{wh.name}</p>
          <Badge
            variant={wh.active ? "default" : "secondary"}
            className={cn(wh.active && "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200")}
          >
            {wh.active ? "Activo" : "Inactivo"}
          </Badge>
          {(wh.failure_count ?? 0) > 0 && (
            <Badge variant="outline" className="text-destructive">
              {wh.failure_count} fallo(s)
            </Badge>
          )}
        </div>
        <p className="text-muted-foreground truncate text-xs">{wh.url}</p>
        <div className="mt-1 flex flex-wrap gap-1">
          {wh.event_types.map((ev) => (
            <Badge key={ev} variant="outline" className="text-xs">
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
              size="sm"
              disabled={form.pingPendiente}
              onClick={() => form.ping(wh.id)}
              aria-label="Enviar entrega de prueba"
            >
              <Radio className="h-4 w-4" aria-hidden="true" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Enviar entrega de prueba</TooltipContent>
        </Tooltip>
        {confirmando && <span className="text-destructive text-xs">¿Confirmar?</span>}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant={confirmando ? "destructive" : "ghost"}
              size="sm"
              className={confirmando ? "" : "text-destructive"}
              disabled={form.borrando}
              onClick={() => form.pedirBorrado(wh.id)}
              aria-label={confirmando ? "Confirmar eliminación de webhook" : "Eliminar webhook"}
            >
              <Trash2 className="h-4 w-4" aria-hidden="true" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            {confirmando ? "Confirmar eliminación" : "Eliminar webhook"}
          </TooltipContent>
        </Tooltip>
        {confirmando && (
          <Button variant="ghost" size="sm" onClick={form.cancelarBorrado}>
            Cancelar
          </Button>
        )}
      </div>
    </div>
  );
}

export function WebhooksCard() {
  const form = useWebhookForm();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <WebhookIcon className="h-5 w-5" />
          Webhooks
        </CardTitle>
        <CardDescription>
          Integraciones salientes — todas las claves admin/sesión admin ven y gestionan los mismos webhooks (no son
          por-usuario).
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {form.newWebhookSecret && (
          <SecretRevealCard
            aviso="Secret generado — cópialo ahora, no se mostrará de nuevo:"
            secret={form.newWebhookSecret}
            onClose={form.clearNewWebhookSecret}
          />
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label htmlFor="wh-name" className="text-sm font-medium">
              Nombre
            </label>
            <Input
              id="wh-name"
              placeholder="p.ej. slack-alertas"
              value={form.whName}
              onChange={(e) => form.setWhName(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="wh-url" className="text-sm font-medium">
              URL
            </label>
            <Input
              id="wh-url"
              placeholder="https://hooks.example.com/licitaciones"
              value={form.whUrl}
              onChange={(e) => form.setWhUrl(e.target.value)}
            />
          </div>
        </div>
        <div className="space-y-1.5">
          <p className="text-sm font-medium">Eventos</p>
          <div className="flex flex-wrap gap-4">
            {WEBHOOK_EVENTS.map((ev) => (
              <label key={ev} className="flex items-center gap-1.5 text-sm">
                <Checkbox
                  checked={form.whEvents.includes(ev)}
                  onCheckedChange={(checked) => form.toggleWhEvent(ev, checked === true)}
                />
                {ev}
              </label>
            ))}
          </div>
        </div>
        <Button
          onClick={form.crear}
          disabled={!form.whName.trim() || !form.whUrl.trim() || form.creando}
          className="gap-1.5"
        >
          <Plus className="h-4 w-4" />
          {form.creando ? "Creando…" : "Crear webhook"}
        </Button>

        <Separator />

        {form.isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-5 w-3/4" />
          </div>
        ) : form.error ? (
          <div className="text-muted-foreground bg-muted/50 flex items-center gap-2 rounded-md p-3 text-sm">
            <Info className="h-4 w-4 shrink-0" />
            <span>{(form.error as Error).message}</span>
          </div>
        ) : !form.webhooks || form.webhooks.length === 0 ? (
          <p className="text-muted-foreground text-sm">No hay webhooks registrados.</p>
        ) : (
          <div className="space-y-2">
            {form.webhooks.map((wh) => (
              <WebhookRow key={wh.id} wh={wh} form={form} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
