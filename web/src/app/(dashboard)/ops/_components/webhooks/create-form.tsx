"use client";

/**
 * Alta de un webhook para una organización.
 *
 * El `secret` llega en la respuesta de creación y no se puede volver a pedir:
 * por eso no se enseña aquí sino que se sube al llamador (`onCreated`), que lo
 * pinta en un aviso persistente.
 *
 * Los valores son los de `WebhookCreate` y se validan con su esquema (S7.2):
 * un nombre vacío o una URL que no sea `https://` se explican debajo de su
 * campo, enlazados a él (`Field`), en vez de volver del backend como 422.
 */

import { Plus } from "lucide-react";
import { Controller, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Panel, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { AYUDA_CAMPO, ETIQUETA_CAMPO, Field } from "@/components/ui/field";
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
import { webhook } from "@/lib/forms/esquemas";
import { cn } from "@/lib/utils";
import { FORMATO_LABEL, FORMATO_VALUES, esFormatoConocido } from "./formato";

const CAMPO_NOMBRE = "webhook-name";
const CAMPO_URL = "webhook-url";
const CAMPO_FORMATO = "webhook-formato";

const VACIO = { name: "", url: "", event_types: [] as string[], formato: "json" as const };

export function CreateForm({
  organizationId,
  onCreated,
}: {
  organizationId: number | null;
  onCreated: (secret: string) => void;
}) {
  const { data: eventTypes = [] } = useWebhookEventTypes();
  const create = useCreateWebhook();
  const form = useForm({ resolver: zodResolver(webhook.esquema), defaultValues: VACIO });
  const errores = form.formState.errors;

  const submit = form.handleSubmit((valores) => {
    create.mutate(
      {
        ...valores,
        event_types: valores.event_types.length ? valores.event_types : ["*"],
        organization_id: organizationId,
      },
      {
        onSuccess: (created) => {
          form.reset(VACIO);
          if (created.secret) onCreated(created.secret);
        },
      },
    );
  });

  return (
    <Panel>
      <PanelTitle title="Nuevo webhook" />
      <form onSubmit={submit} noValidate className="space-y-3">
        <div className="grid items-start gap-3 md:grid-cols-2 lg:grid-cols-[1fr_1.5fr_200px_200px]">
          <Field label="Nombre del webhook" htmlFor={CAMPO_NOMBRE} error={errores.name?.message}>
            <Input
              id={CAMPO_NOMBRE}
              {...form.register("name")}
              placeholder="p. ej. Alertas en Slack"
              required
              maxLength={100}
            />
          </Field>
          <Field label="URL de destino" htmlFor={CAMPO_URL} error={errores.url?.message}>
            <Input id={CAMPO_URL} {...form.register("url")} placeholder="https://…" type="url" required />
          </Field>
          <div className="space-y-1.5">
            {/* El control ya se llama «Eventos a los que suscribirse»: la
                etiqueta visible es la misma palabra y no se lee dos veces. */}
            <p className={ETIQUETA_CAMPO} aria-hidden="true">
              Eventos
            </p>
            <Controller
              control={form.control}
              name="event_types"
              render={({ field }) => (
                <MultiSelect
                  aria-label="Eventos a los que suscribirse"
                  options={eventTypes}
                  selected={field.value}
                  onChange={field.onChange}
                  placeholder="Todos los eventos"
                />
              )}
            />
          </div>
          <Field label="Formato del mensaje" htmlFor={CAMPO_FORMATO}>
            <Controller
              control={form.control}
              name="formato"
              render={({ field }) => (
                <Select
                  value={field.value}
                  // `Select` entrega un `string`: se estrecha contra la lista de
                  // formatos en vez de castear, para que un valor que el backend no
                  // acepte no llegue nunca al cuerpo de la petición.
                  onValueChange={(value) => {
                    if (esFormatoConocido(value)) field.onChange(value);
                  }}
                >
                  <SelectTrigger id={CAMPO_FORMATO}>
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
              )}
            />
          </Field>
        </div>
        <Button type="submit" size="sm" disabled={create.isPending}>
          <Plus aria-hidden="true" />
          Crear webhook
        </Button>
      </form>
      <p className={cn(AYUDA_CAMPO, "mt-3")}>
        La URL debe ser <code className="font-mono">https://</code>. Cada entrega va firmada con HMAC para que tu
        sistema pueda comprobar que viene de TenderFlow. Con Slack o Teams, pega la URL del <em>incoming webhook</em>{" "}
        del canal y elige su formato: el mensaje llega ya maquetado.
      </p>
    </Panel>
  );
}
