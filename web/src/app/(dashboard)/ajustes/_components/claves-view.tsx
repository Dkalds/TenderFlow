"use client";

/**
 * Claves de API — crearlas desde el producto, con su tier (C2.3, D25).
 *
 * `/me/keys` listaba y rotaba, pero **no creaba**: para tener una clave había
 * que ejecutar un script del repositorio. Y `api_key_tiers` existía desde `v28`
 * con su columna en `api_keys` sin que ninguna ruta ni middleware la leyera, así
 * que el límite de una clave se descubría por un 429.
 *
 * El secreto se enseña **una sola vez**, en un aviso que no desaparece solo: no
 * hay endpoint que lo vuelva a exponer, y un toast efímero para un valor
 * irrecuperable sería una trampa. Mismo criterio que la pantalla de webhooks.
 */

import * as React from "react";
import { Copy, Plus } from "lucide-react";
import { toast } from "sonner";
import { Aviso, Panel, PanelEmpty, PanelError, PanelTitle } from "@/components/console/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { type CreatedKey, useClaves, useCrearClave } from "@/hooks/use-ajustes";
import { formatDateTime } from "@/lib/utils";

const EMPTY = "—";

function fecha(valor: string | null | undefined): string {
  if (!valor) return EMPTY;
  const d = new Date(valor);
  return Number.isNaN(d.getTime()) ? EMPTY : formatDateTime(d);
}

/** Aviso persistente con la clave recién creada: no se puede volver a ver. */
function SecretoNuevo({ clave, onCerrar }: { clave: CreatedKey; onCerrar: () => void }) {
  return (
    <Aviso tone="warning" role="alert" title="Guarda esta clave ahora">
      <p className="text-muted-foreground">No se puede volver a ver. Si la pierdes, tendrás que crear otra.</p>
      <code className="bg-muted mt-2 block overflow-x-auto rounded-sm p-2 font-mono text-tf-meta">
        {clave.api_key}
      </code>
      <div className="mt-2 flex gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            void navigator.clipboard.writeText(clave.api_key ?? "");
            toast.success("Clave copiada");
          }}
        >
          <Copy aria-hidden="true" />
          Copiar
        </Button>
        <Button size="sm" variant="ghost" onClick={onCerrar}>
          Ya la he guardado
        </Button>
      </div>
    </Aviso>
  );
}

export default function ClavesView() {
  const { data, isLoading, error, refetch } = useClaves();
  const crear = useCrearClave();
  const [nombre, setNombre] = React.useState("");
  const [reciente, setReciente] = React.useState<CreatedKey | null>(null);

  const claves = data?.items ?? [];

  const crearClave = () => {
    const limpio = nombre.trim();
    if (!limpio) {
      toast.error("Ponle un nombre para reconocerla después");
      return;
    }
    crear.mutate(
      { name: limpio },
      {
        onSuccess: (nueva) => {
          setReciente(nueva);
          setNombre("");
        },
      },
    );
  };

  return (
    <div className="space-y-4">
      {reciente ? <SecretoNuevo clave={reciente} onCerrar={() => setReciente(null)} /> : null}

      <Panel>
        <PanelTitle title="Nueva clave" />
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Nombre" htmlFor="nombre-clave" className="min-w-[220px] flex-1">
            <Input
              id="nombre-clave"
              value={nombre}
              maxLength={80}
              placeholder="p. ej. Integración con nuestro CRM"
              onChange={(e) => setNombre(e.target.value)}
            />
          </Field>
          <Button size="sm" onClick={crearClave} disabled={crear.isPending}>
            <Plus aria-hidden="true" />
            Crear
          </Button>
        </div>
      </Panel>

      <Panel>
        <PanelTitle title={`Tus claves (${claves.length})`} />
        {isLoading ? (
          <Skeleton className="h-20 w-full rounded-md" />
        ) : error ? (
          <PanelError
            variant="inline"
            title="No se pudieron cargar tus claves"
            error={error}
            onRetry={() => void refetch()}
          />
        ) : claves.length === 0 ? (
          <PanelEmpty
            size="sm"
            title="Todavía no tienes ninguna clave"
            hint="Con una clave de API, tus sistemas consultan TenderFlow sin pasar por el navegador."
          />
        ) : (
          <ul className="space-y-2">
            {claves.map((clave) => (
              <li key={clave.id} className="rounded-md border border-border/60 p-3">
                <p className="flex flex-wrap items-center gap-2 text-tf-body font-medium">
                  {clave.name || `Clave ${clave.id}`}
                  <Badge variant="secondary" size="sm">
                    {clave.tier}
                  </Badge>
                  {clave.is_active ? null : (
                    <Badge variant="outline" size="sm">
                      Inactiva
                    </Badge>
                  )}
                </p>
                <p className="text-muted-foreground mt-1 text-tf-meta">
                  Creada {fecha(clave.created_at)}
                  {clave.expires_at ? ` · Caduca ${fecha(clave.expires_at)}` : ""}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
