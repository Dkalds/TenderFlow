"use client";

/**
 * Identidad fiscal de la organización (S2.1).
 *
 * Es la pantalla que hace que el cierre de una oportunidad deje de teclearse:
 * con los NIFs declarados, la ficha propone `won`/`lost` preseleccionado y
 * «contra quién» excluye a la propia casa de su ranking de competidores.
 *
 * Edita la lista entera y la manda entera, igual que el PUT del backend: no
 * hay alta ni borrado por fila. El botón «Guardar» aparece solo cuando hay un
 * cambio real, para que nadie escriba sin querer sobre lo que ya estaba bien.
 */

import * as React from "react";
import { Check, Loader2, Plus, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type OrganizationNifIn,
  useOrganizationNifs,
  useSaveOrganizationNifs,
} from "../_hooks/use-organization-capacidad";

function aBorrador(nifs: OrganizationNifIn[]): OrganizationNifIn[] {
  return nifs.map((fila) => ({
    nif: fila.nif,
    razon_social: fila.razon_social ?? "",
    principal: fila.principal,
  }));
}

export function OrganizacionNifsCard({
  organizationId,
  canManage,
}: {
  organizationId: number;
  canManage: boolean;
}) {
  const nifs = useOrganizationNifs(organizationId, canManage);
  const guardar = useSaveOrganizationNifs(organizationId);
  const [borrador, setBorrador] = React.useState<OrganizationNifIn[] | null>(null);

  const persistidos = React.useMemo(() => aBorrador(nifs.data?.nifs ?? []), [nifs.data]);
  const filas = borrador ?? persistidos;
  const sucio = JSON.stringify(filas) !== JSON.stringify(persistidos);

  const actualizar = (indice: number, cambio: Partial<OrganizationNifIn>) => {
    setBorrador(filas.map((fila, i) => (i === indice ? { ...fila, ...cambio } : fila)));
  };

  const marcarPrincipal = (indice: number) => {
    // Uno solo: el backend rechaza dos principales con un 422, así que la UI
    // no ofrece siquiera ese estado.
    setBorrador(filas.map((fila, i) => ({ ...fila, principal: i === indice })));
  };

  const submit = async () => {
    try {
      await guardar.mutateAsync(
        filas
          .filter((fila) => fila.nif.trim())
          .map((fila) => ({
            nif: fila.nif.trim(),
            razon_social: fila.razon_social?.trim() || null,
            principal: fila.principal,
          })),
      );
      setBorrador(null);
      toast.success("Identidad fiscal guardada");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "No se pudieron guardar los NIFs");
    }
  };

  if (!canManage) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Identidad fiscal</CardTitle>
          <CardDescription>
            Solo el propietario o un administrador pueden ver y editar los NIFs con los que la
            organización concurre.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Identidad fiscal</CardTitle>
        <CardDescription>
          Los NIFs con los que la organización se presenta. Con ellos, la ficha de una oportunidad
          propone si la ganasteis vosotros y el análisis de competencia deja de contaros como
          competidores de vosotros mismos.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {nifs.isLoading ? (
          <Skeleton className="h-10 w-full" />
        ) : (
          <>
            {filas.length === 0 && (
              <p className="text-sm text-muted-foreground">
                Todavía no hay ningún NIF declarado: el cierre de las oportunidades se seguirá
                marcando a mano.
              </p>
            )}
            {filas.map((fila, indice) => (
              <div key={indice} className="flex flex-wrap items-end gap-2">
                <label
                  className="min-w-40 flex-1 space-y-1.5 text-sm font-medium"
                  htmlFor={`nif-${indice}`}
                >
                  NIF / CIF
                  <Input
                    id={`nif-${indice}`}
                    value={fila.nif}
                    // Formato de ejemplo de un CIF español, no una credencial:
                    // detect-secrets lo lee como cadena hexadecimal.
                    placeholder="B12345678" // pragma: allowlist secret
                    onChange={(event) => actualizar(indice, { nif: event.target.value })}
                  />
                </label>
                <label
                  className="min-w-56 flex-[2] space-y-1.5 text-sm font-medium"
                  htmlFor={`razon-social-${indice}`}
                >
                  Razón social
                  <Input
                    id={`razon-social-${indice}`}
                    value={fila.razon_social ?? ""}
                    placeholder="Acme Consulting SL"
                    onChange={(event) => actualizar(indice, { razon_social: event.target.value })}
                  />
                </label>
                <Button
                  type="button"
                  size="sm"
                  variant={fila.principal ? "default" : "outline"}
                  onClick={() => marcarPrincipal(indice)}
                >
                  {fila.principal ? <Check className="h-4 w-4" /> : null}
                  Principal
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  aria-label={`Quitar ${fila.nif || "el NIF"}`}
                  onClick={() => setBorrador(filas.filter((_, i) => i !== indice))}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
            {(nifs.data?.nifs ?? []).some((fila) => fila.empresa_id != null) && (
              <Badge variant="secondary">
                Enlazado con el maestro de empresas: se excluye de «contra quién»
              </Badge>
            )}
            <div className="flex gap-2 pt-1">
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() =>
                  setBorrador([...filas, { nif: "", razon_social: "", principal: false }])
                }
              >
                <Plus className="h-4 w-4" />
                Añadir NIF
              </Button>
              {sucio && (
                <Button type="button" size="sm" onClick={submit} disabled={guardar.isPending}>
                  {guardar.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Save className="h-4 w-4" />
                  )}
                  Guardar
                </Button>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
