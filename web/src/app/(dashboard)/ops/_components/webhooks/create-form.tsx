"use client";

/**
 * Alta de un webhook para una organización.
 *
 * El `secret` llega en la respuesta de creación y no se puede volver a pedir:
 * por eso no se enseña aquí sino que se sube al llamador (`onCreated`), que lo
 * pinta en un aviso persistente.
 */

import * as React from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { MultiSelect } from "@/components/ui/multi-select";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCreateWebhook, useWebhookEventTypes } from "@/hooks/use-webhooks";
import { FORMATO_LABEL, FORMATO_VALUES, esFormatoConocido, type FormatoWebhook } from "./formato";

export function CreateForm({
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
  const [formato, setFormato] = React.useState<FormatoWebhook>("json");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    create.mutate(
      {
        name: name.trim(),
        url: url.trim(),
        event_types: events.length ? events : ["*"],
        formato,
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
          <Select
            value={formato}
            // `Select` entrega un `string`: se estrecha contra la lista de
            // formatos en vez de castear, para que un valor que el backend no
            // acepte no llegue nunca al cuerpo de la petición.
            onValueChange={(value) => {
              if (esFormatoConocido(value)) setFormato(value);
            }}
          >
            <SelectTrigger aria-label="Formato del mensaje">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {FORMATO_VALUES.map((value) => (
                <SelectItem key={value} value={value}>
                  {FORMATO_LABEL[value]}
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
