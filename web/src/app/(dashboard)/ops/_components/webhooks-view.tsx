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
 *
 * **Dos vistas desde el mismo componente (S4.2).** Un webhook ya no es un
 * recurso de instancia: pertenece a una organización y lo gestiona cualquier
 * miembro con permiso de escritura.
 *
 * - `WebhooksEquipoView` es la de `/equipo`: los webhooks de TU organización,
 *   con alta, edición y ping. Es la que usa el 99% de la gente.
 * - `WebhooksView` (el default, `/ops`) es la vista **global** del
 *   administrador de la instancia: todas las filas, incluidas las que no
 *   tienen dueño (las anteriores a la revisión `v108`), en modo lectura de
 *   estado. Se conserva porque esas integraciones sin organización siguen
 *   entregando y alguien tiene que poder verlas.
 *
 * Los datos se piden aquí y no con `@/hooks/use-webhooks` porque ese hook
 * describe el listado de instancia y ahora hay dos ámbitos distintos; cuando
 * el cliente generado se regenere con `organization_id` y `formato`, estas
 * consultas se mudan allí sin cambiar la pantalla.
 */

import * as React from "react";
import { AlertTriangle, Copy, Plus, Send, Trash2 } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { MultiSelect } from "@/components/ui/multi-select";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
} from "@/hooks/use-webhooks";
import { useActiveOrganizationId } from "@/hooks/use-organization";
import { fetchWithAuth } from "@/lib/api-client";
import { webhookKeys } from "@/lib/query-keys";
import { toast } from "sonner";
import { formatDateTime } from "@/lib/utils";

const EMPTY = "—";

/**
 * Formatos de plantilla (D13). El backend los sirve en
 * `GET /webhooks/event-types` junto a los tipos; esta lista es solo el
 * ETIQUETADO en castellano, que no es dato sino copy — el valor válido lo
 * sigue decidiendo el backend.
 */
const FORMATO_LABEL: Record<string, string> = {
  json: "JSON (genérico)",
  slack_blocks: "Slack · Block Kit",
  teams_adaptive_card: "Teams · Adaptive Card",
};

/**
 * Campos que la API ya devuelve y el cliente generado todavía no describe
 * (`npm run codegen:file` los incorpora en cuanto se regenera desde el
 * OpenAPI de esta rama). Se declaran opcionales a propósito: la pantalla
 * compila y funciona con el cliente viejo y con el nuevo, y no hay que
 * duplicar la forma entera del DTO —que es el anti-patrón de ADR-014.
 */
type WebhookAmpliado = WebhookOut & {
  organization_id?: number | null;
  created_by?: number | null;
  formato?: string | null;
};

function formatDate(value: string | null | undefined): string {
  if (!value) return EMPTY;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? EMPTY : formatDateTime(date);
}

/** Webhooks de una organización (los que gestiona un equipo desde `/equipo`). */
function useWebhooksDeEquipo(organizationId: number | null) {
  return useQuery({
    queryKey: [...webhookKeys.all, "organizacion", organizationId] as const,
    queryFn: () =>
      fetchWithAuth<WebhookAmpliado[]>(
        organizationId == null
          ? "/api/v1/webhooks"
          : `/api/v1/webhooks?organization_id=${organizationId}`,
      ),
  });
}

/** Todos los webhooks de la instancia. Solo administradores; vista de `/ops`. */
function useWebhooksGlobales() {
  return useQuery({
    queryKey: [...webhookKeys.all, "global"] as const,
    queryFn: () => fetchWithAuth<WebhookAmpliado[]>("/api/v1/webhooks/global"),
  });
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

function WebhookRow({ webhook, editable }: { webhook: WebhookAmpliado; editable: boolean }) {
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

function CreateForm({
  organizationId,
  onCreated,
}: {
  organizationId: number | null;
  onCreated: (secret: string) => void;
}) {
  const { data: eventTypes = [] } = useWebhookEventTypes();
  const create = useCreateWebhook();
  const [name, setName] = React.useState("");
  const [url, setUrl] = React.useState("");
  const [events, setEvents] = React.useState<string[]>([]);
  const [formato, setFormato] = React.useState("json");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    create.mutate(
      {
        name: name.trim(),
        url: url.trim(),
        event_types: events.length ? events : ["*"],
        formato: formato as "json" | "slack_blocks" | "teams_adaptive_card",
        organization_id: organizationId,
      },
      {
        onSuccess: (created) => {
          setName("");
          setUrl("");
          setEvents([]);
          setFormato("json");
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
        <form onSubmit={submit} className="grid gap-3 md:grid-cols-[1fr_1.5fr_200px_200px_auto]">
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
          <Select value={formato} onValueChange={setFormato}>
            <SelectTrigger aria-label="Formato del mensaje">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(FORMATO_LABEL).map(([value, label]) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button type="submit" disabled={create.isPending}>
            <Plus className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
            Crear
          </Button>
        </form>
        <p className="text-muted-foreground mt-2 text-xs">
          La URL debe ser <code className="font-mono">https://</code>. Cada entrega va firmada con HMAC para que tu
          sistema pueda verificar que viene de aquí. Con Slack o Teams, pegá la URL del <em>incoming webhook</em> del
          canal y elegí su formato: el mensaje llega ya maquetado.
        </p>
      </CardContent>
    </Card>
  );
}

function Listado({
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

/**
 * Webhooks del equipo. Es lo que se monta en `/equipo` para `owner`/`admin`.
 *
 * Vive en este fichero y no en `equipo/` porque la maquinaria (alta con
 * secret, ping, historial de entregas) es exactamente la misma que la vista
 * global y duplicarla habría dejado dos pantallas que se desincronizan.
 */
export function WebhooksEquipoView() {
  const organizationId = useActiveOrganizationId();
  const { data, isPending, error } = useWebhooksDeEquipo(organizationId);
  const [newSecret, setNewSecret] = React.useState<string | null>(null);

  return (
    <div className="mx-auto w-full max-w-4xl space-y-4 p-4">
      {newSecret && <SecretNotice secret={newSecret} onDismiss={() => setNewSecret(null)} />}

      <CreateForm organizationId={organizationId} onCreated={setNewSecret} />

      <Listado
        webhooks={data}
        isPending={isPending}
        error={error}
        editable
        vacio="Creá uno para recibir en Slack, en Teams o en tus propios sistemas lo que pasa en vuestras oportunidades."
      />
    </div>
  );
}

/**
 * Vista global de `/ops`: todos los webhooks de la instancia, en lectura.
 *
 * No permite crear ni editar a propósito. Crear un webhook exige decir a qué
 * organización pertenece, y esa decisión se toma dentro del equipo (en
 * `/equipo`), no desde una consola que ve todas las organizaciones a la vez.
 * Lo que esta vista sí resuelve es lo que ninguna otra puede: ver las
 * integraciones **sin dueño** heredadas de antes de `v108` y el estado de
 * entrega de todo el conjunto.
 */
export default function WebhooksView() {
  const { data, isPending, error } = useWebhooksGlobales();

  return (
    <div className="mx-auto w-full max-w-4xl space-y-4 p-4">
      <p className="text-muted-foreground text-xs">
        Vista global de la instancia, en solo lectura. Cada equipo gestiona los suyos desde <strong>Equipo →
        Integraciones</strong>; aquí aparecen además los que no tienen organización, heredados de antes de que los
        webhooks tuvieran dueño.
      </p>

      <Listado
        webhooks={data}
        isPending={isPending}
        error={error}
        editable={false}
        vacio="No hay ningún webhook registrado en la instancia."
      />
    </div>
  );
}
