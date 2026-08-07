"use client";

/**
 * Webhooks — integración de alertas con los sistemas del cliente.
 *
 * El backend llevaba tiempo completo (firma HMAC, reintentos con backoff,
 * DNS-pinning, historial de entregas) y no había forma de usarlo sin llamar a
 * la API a mano. Esta pantalla es esa superficie.
 *
 * Decisión de diseño: el `secret` se enseña **una sola vez**, en un aviso que
 * no desaparece solo, porque no hay endpoint que lo vuelva a exponer. Un toast
 * efímero para un valor irrecuperable sería una trampa.
 */

import * as React from "react";
import { AlertTriangle, Copy, Plus, Send, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { MultiSelect } from "@/components/ui/multi-select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  type WebhookOut,
  useCreateWebhook,
  useDeleteWebhook,
  useWebhookDeliveries,
  usePingWebhook,
  useUpdateWebhook,
  useWebhookEventTypes,
  useWebhooks,
} from "@/hooks/use-webhooks";
import { toast } from "sonner";

const EMPTY = "—";

function formatDate(value: string | null | undefined): string {
  if (!value) return EMPTY;
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? EMPTY
    : date.toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" });
}

/** Aviso persistente con el secret recién creado: no se puede volver a ver. */
function SecretNotice({ secret, onDismiss }: { secret: string; onDismiss: () => void }) {
  return (
    <div role="alert" className="border-warning/40 bg-warning/10 mb-4 rounded-lg border p-4 text-sm">
      <div className="flex items-start gap-2">
        <AlertTriangle className="text-warning mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="font-medium">Guardá este secret ahora</p>
          <p className="text-muted-foreground mt-1 text-xs">
            Es la única vez que se muestra: sirve para verificar la firma HMAC de cada entrega y no hay forma de
            recuperarlo después.
          </p>
          <code className="bg-background mt-2 block truncate rounded border px-2 py-1.5 font-mono text-xs">
            {secret}
          </code>
          <div className="mt-2 flex gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                void navigator.clipboard?.writeText(secret);
                toast.success("Secret copiado al portapapeles");
              }}
            >
              <Copy className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
              Copiar
            </Button>
            <Button size="sm" variant="ghost" onClick={onDismiss}>
              Ya lo guardé
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function DeliveriesPanel({ webhookId }: { webhookId: number }) {
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

function WebhookRow({ webhook }: { webhook: WebhookOut }) {
  const [open, setOpen] = React.useState(false);
  const update = useUpdateWebhook();
  const remove = useDeleteWebhook();
  const ping = usePingWebhook();

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 pb-3">
        <div className="min-w-0">
          <CardTitle className="text-sm">{webhook.name}</CardTitle>
          <p className="text-muted-foreground mt-1 truncate font-mono text-xs">{webhook.url}</p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {(webhook.event_types ?? []).map((event) => (
              <Badge key={event} variant="secondary" className="font-mono text-[10px]">
                {event}
              </Badge>
            ))}
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

function CreateForm({ onCreated }: { onCreated: (secret: string) => void }) {
  const { data: eventTypes = [] } = useWebhookEventTypes();
  const create = useCreateWebhook();
  const [name, setName] = React.useState("");
  const [url, setUrl] = React.useState("");
  const [events, setEvents] = React.useState<string[]>([]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    create.mutate(
      { name: name.trim(), url: url.trim(), event_types: events.length ? events : ["*"] },
      {
        onSuccess: (created) => {
          setName("");
          setUrl("");
          setEvents([]);
          if (created.secret) onCreated(created.secret);
        },
      },
    );
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm">Nuevo webhook</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="grid gap-3 md:grid-cols-[1fr_1.5fr_200px_auto]">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Nombre"
            aria-label="Nombre del webhook"
            required
            maxLength={100}
          />
          <Input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://…"
            aria-label="URL de destino"
            type="url"
            required
          />
          <MultiSelect
            aria-label="Eventos a los que suscribirse"
            options={eventTypes}
            selected={events}
            onChange={setEvents}
            placeholder="Todos los eventos"
          />
          <Button type="submit" disabled={create.isPending}>
            <Plus className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
            Crear
          </Button>
        </form>
        <p className="text-muted-foreground mt-2 text-xs">
          La URL debe ser <code className="font-mono">https://</code>. Cada entrega va firmada con HMAC para que tu
          sistema pueda verificar que viene de aquí.
        </p>
      </CardContent>
    </Card>
  );
}

export default function WebhooksPage() {
  const { data: webhooks, isPending, error } = useWebhooks();
  const [newSecret, setNewSecret] = React.useState<string | null>(null);

  return (
    <div className="mx-auto w-full max-w-4xl space-y-4 p-4">
      {newSecret && <SecretNotice secret={newSecret} onDismiss={() => setNewSecret(null)} />}

      <CreateForm onCreated={setNewSecret} />

      {error && (
        <div role="alert" className="text-destructive text-sm">
          No se pudieron cargar los webhooks.
        </div>
      )}

      {isPending && <Skeleton className="h-24 w-full" />}

      {!isPending && !error && !webhooks?.length && (
        <EmptyState title="Sin webhooks" hint="Creá uno para recibir las alertas en tus propios sistemas." />
      )}

      <div className="space-y-3">
        {webhooks?.map((webhook) => (
          <WebhookRow key={webhook.id} webhook={webhook} />
        ))}
      </div>
    </div>
  );
}
