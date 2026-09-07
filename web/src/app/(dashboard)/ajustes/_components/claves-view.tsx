"use client";

import { useState } from "react";
import { Panel, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useCrearClave } from "@/hooks/use-cuenta";

/**
 * Claves de API — acuñar una sin pedírsela al mantenedor (C2.3).
 *
 * `create_api_key` existía y **sólo la usaba un script**: `/me/keys` listaba y
 * rotaba, pero no creaba. Para tener una clave había que abrir un ticket.
 *
 * El secreto se enseña **una vez**. No es una molestia de diseño: el backend
 * guarda el hash, así que no hay ningún sitio del que volver a sacarlo, y
 * prometer lo contrario con un «ver clave» que devolviera algo significaría que
 * está almacenada en claro.
 */

export default function ClavesView() {
  const crear = useCrearClave();
  const [nombre, setNombre] = useState("");
  const [secreto, setSecreto] = useState<string | null>(null);
  const [copiado, setCopiado] = useState(false);

  const enviar = (event: React.FormEvent) => {
    event.preventDefault();
    if (!nombre.trim()) return;
    crear.mutate(
      { name: nombre.trim() },
      {
        onSuccess: (respuesta) => {
          const clave = (respuesta as { api_key?: string } | null)?.api_key ?? null;
          setSecreto(clave);
          setNombre("");
        },
      },
    );
  };

  return (
    <div className="space-y-4">
      <Panel>
        <PanelTitle
          title="Nueva clave de API"
          hint="Exige haber entrado hace poco: una clave sobrevive al cierre de sesión"
        />
        <form onSubmit={enviar} className="flex flex-wrap items-end gap-2">
          <div className="min-w-56 flex-1">
            <label htmlFor="clave-nombre" className="mb-1 block text-[11px] text-muted-foreground">
              Para qué es
            </label>
            <Input
              id="clave-nombre"
              value={nombre}
              onChange={(event) => setNombre(event.target.value)}
              placeholder="Integración con el CRM"
              maxLength={120}
            />
          </div>
          <Button type="submit" disabled={!nombre.trim() || crear.isPending}>
            {crear.isPending ? "Creando…" : "Crear clave"}
          </Button>
        </form>
        <p className="mt-2 text-[10.5px] leading-[1.5] text-muted-foreground">
          Los permisos de la clave no pueden superar los de tu cuenta. Los scopes de
          administración están reservados.
        </p>
        {crear.isError && (
          <p className="mt-2 text-[11px] text-destructive">
            No se pudo crear la clave. Si hace rato que entraste, volvé a iniciar sesión.
          </p>
        )}
      </Panel>

      {secreto && (
        <Panel className="border-primary/50 bg-primary/5">
          <PanelTitle title="Copiala ahora" hint="No se vuelve a mostrar" />
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded-md border border-border/60 bg-background px-2 py-1.5 font-mono text-[11px]">
              {secreto}
            </code>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                void navigator.clipboard?.writeText(secreto);
                setCopiado(true);
              }}
            >
              {copiado ? "Copiada" : "Copiar"}
            </Button>
          </div>
          <p className="mt-2 text-[10.5px] leading-[1.5] text-muted-foreground">
            El servidor guarda sólo un hash. Si la perdés, hay que rotarla: no existe ningún
            sitio del que recuperarla.
          </p>
        </Panel>
      )}
    </div>
  );
}
