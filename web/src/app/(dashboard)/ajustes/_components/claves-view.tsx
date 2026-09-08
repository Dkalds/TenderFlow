"use client";

/**
 * API keys — crearlas desde el producto, con su tier (C2.3, D25).
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
import { AlertTriangle, Copy, KeyRound, Plus } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
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
    <div role="alert" className="border-warning/40 bg-warning/10 mb-4 rounded-lg border p-4 text-sm">
      <div className="flex items-start gap-2">
        <AlertTriangle className="text-warning mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="font-medium">Guardá esta clave ahora</p>
          <p className="text-muted-foreground mt-1 text-xs">
            No se puede volver a ver. Si la perdés, hay que crear otra.
          </p>
          <code className="bg-muted mt-2 block overflow-x-auto rounded p-2 font-mono text-xs">
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
              <Copy className="h-3.5 w-3.5" aria-hidden="true" />
              Copiar
            </Button>
            <Button size="sm" variant="ghost" onClick={onCerrar}>
              Ya la he guardado
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ClavesView() {
  const { data, isLoading, isError } = useClaves();
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

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <KeyRound className="h-4 w-4" aria-hidden="true" />
            Nueva clave
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-2">
          <div className="min-w-[220px] flex-1">
            <label htmlFor="nombre-clave" className="mb-1 block text-xs font-medium">
              Nombre
            </label>
            <Input
              id="nombre-clave"
              value={nombre}
              maxLength={80}
              placeholder="Integración con nuestro CRM"
              onChange={(e) => setNombre(e.target.value)}
            />
          </div>
          <Button onClick={crearClave} disabled={crear.isPending}>
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            Crear
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Tus claves ({claves.length})</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-20 w-full rounded-lg" />
          ) : isError ? (
            <EmptyState
              title="No se pudieron cargar tus claves"
              hint="Volvé a intentarlo en un momento."
            />
          ) : claves.length === 0 ? (
            <EmptyState
              title="Todavía no tienes ninguna clave"
              hint="Una clave de API deja que tus sistemas consulten TenderFlow sin pasar por el navegador."
            />
          ) : (
            <div className="space-y-2">
              {claves.map((clave) => (
                <div
                  key={clave.id}
                  className="border-border flex items-start justify-between gap-3 rounded-lg border p-3"
                >
                  <div className="min-w-0">
                    <p className="flex items-center gap-2 text-sm font-medium">
                      {clave.name || `Clave ${clave.id}`}
                      <Badge variant="secondary" className="text-[10px]">
                        {clave.tier}
                      </Badge>
                      {clave.is_active ? null : (
                        <Badge variant="outline" className="text-[10px]">
                          Inactiva
                        </Badge>
                      )}
                    </p>
                    <p className="text-muted-foreground mt-1 text-xs">
                      Creada {fecha(clave.created_at)}
                      {clave.expires_at ? ` · Caduca ${fecha(clave.expires_at)}` : ""}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
