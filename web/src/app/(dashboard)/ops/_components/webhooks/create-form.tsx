"use client";

/**
 * Alta de un webhook para una organización.
 *
 * El `secret` llega en la respuesta de creación y no se puede volver a pedir:
 * por eso no se enseña aquí sino que se sube al llamador (`onCreated`), que lo
 * pinta en un aviso persistente.
 *
 * Los valores son los de `WebhookCreate` y se validan con su esquema (S7.2):
 * un nombre vacío o una URL que no sea `https://` se explican debajo del
 * formulario, enlazados a su campo, en vez de volver del backend como 422.
 */

import { Plus } from "lucide-react";
import { Controller, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
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
import { ariaCampo, CampoError } from "@/lib/forms/campo";
import { webhook } from "@/lib/forms/esquemas";
import { FORMATO_LABEL, FORMATO_VALUES, esFormatoConocido } from "./formato";

const CAMPO_NOMBRE = "webhook-name";
const CAMPO_URL = "webhook-url";

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
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm">Nuevo webhook</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} noValidate className="grid gap-3 md:grid-cols-[1fr_1.5fr_200px_200px_auto]">
          <Input
            id={CAMPO_NOMBRE}
            {...form.register("name")}
            placeholder="Nombre"
            aria-label="Nombre del webhook"
            required
            maxLength={100}
            {...ariaCampo(CAMPO_NOMBRE, errores.name?.message)}
          />
          <Input
            id={CAMPO_URL}
            {...form.register("url")}
            placeholder="https://…"
            aria-label="URL de destino"
            type="url"
            required
            {...ariaCampo(CAMPO_URL, errores.url?.message)}
          />
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
            )}
          />
          <Button type="submit" disabled={create.isPending}>
            <Plus className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
            Crear
          </Button>
        </form>
        {/* Debajo de la rejilla y no en ella: una sexta celda descuadraría las
            columnas. Cada mensaje lleva el id que su campo nombra. */}
        {(errores.name || errores.url) && (
          <div className="mt-2 space-y-1">
            <CampoError campoId={CAMPO_NOMBRE} mensaje={errores.name?.message} />
            <CampoError campoId={CAMPO_URL} mensaje={errores.url?.message} />
          </div>
        )}
        <p className="text-muted-foreground mt-2 text-xs">
          La URL debe ser <code className="font-mono">https://</code>. Cada entrega va firmada con HMAC para que tu
          sistema pueda verificar que viene de aquí. Con Slack o Teams, pegá la URL del <em>incoming webhook</em> del
          canal y elegí su formato: el mensaje llega ya maquetado.
        </p>
      </CardContent>
    </Card>
  );
}
