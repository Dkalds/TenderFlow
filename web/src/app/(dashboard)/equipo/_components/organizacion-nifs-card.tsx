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
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Panel, PanelError, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type OrganizationNifIn,
  useOrganizationNifs,
  useSaveOrganizationNifs,
} from "../_hooks/use-organization-capacidad";
import { getErrorMessage } from "@/lib/query-feedback";

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
      toast.error(getErrorMessage(error, "accion"));
    }
  };

  if (!canManage) {
    return (
      <Panel>
        <PanelTitle title="Identidad fiscal" />
        <p className="text-tf-meta text-muted-foreground">
          Solo el propietario o un administrador pueden ver y editar los NIF con los que la organización concurre.
        </p>
      </Panel>
    );
  }

  return (
    <Panel>
      <PanelTitle title="Identidad fiscal" />
      <p className="mb-3 text-tf-meta text-muted-foreground">
        Los NIF con los que la organización se presenta. Con ellos, la ficha de una oportunidad propone si la ganó
        tu organización y el análisis de competencia deja de contarla como competidora de sí misma.
      </p>
      <div className="space-y-3">
        {nifs.isLoading ? (
          <Skeleton className="h-10 w-full" />
        ) : nifs.error ? (
          // Sin esto, un fallo al leer se pintaba como «ningún NIF declarado» y
          // el formulario invitaba a declarar de nuevo lo que ya estaba.
          <PanelError
            variant="inline"
            title="No se pudo cargar la identidad fiscal"
            error={nifs.error}
            onRetry={() => void nifs.refetch()}
          />
        ) : (
          <>
            {filas.length === 0 && (
              <p className="text-tf-meta text-muted-foreground">
                Todavía no hay ningún NIF declarado: el cierre de las oportunidades se seguirá marcando a mano.
              </p>
            )}
            {filas.map((fila, indice) => (
              <div key={indice} className="flex flex-wrap items-end gap-2">
                <Field label="NIF / CIF" htmlFor={`nif-${indice}`} className="min-w-40 flex-1">
                  <Input
                    id={`nif-${indice}`}
                    value={fila.nif}
                    className="font-mono"
                    // Formato de ejemplo de un CIF español, no una credencial:
                    // detect-secrets lo lee como cadena hexadecimal.
                    placeholder="B12345678" // pragma: allowlist secret
                    onChange={(event) => actualizar(indice, { nif: event.target.value })}
                  />
                </Field>
                <Field label="Razón social" htmlFor={`razon-social-${indice}`} className="min-w-56 flex-[2]">
                  <Input
                    id={`razon-social-${indice}`}
                    value={fila.razon_social ?? ""}
                    placeholder="Acme Consulting SL"
                    onChange={(event) => actualizar(indice, { razon_social: event.target.value })}
                  />
                </Field>
                <Button
                  type="button"
                  variant={fila.principal ? "default" : "outline"}
                  aria-pressed={fila.principal}
                  onClick={() => marcarPrincipal(indice)}
                >
                  Principal
                </Button>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  aria-label={`Quitar ${fila.nif || "el NIF"}`}
                  onClick={() => setBorrador(filas.filter((_, i) => i !== indice))}
                >
                  <Trash2 aria-hidden="true" />
                </Button>
              </div>
            ))}
            {(nifs.data?.nifs ?? []).some((fila) => fila.empresa_id != null) && (
              <p className="text-tf-meta text-muted-foreground">
                Enlazado con el maestro de empresas: tu organización ya no sale como competidora en «contra quién».
              </p>
            )}
            <div className="flex gap-2 pt-1">
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => setBorrador([...filas, { nif: "", razon_social: "", principal: false }])}
              >
                <Plus aria-hidden="true" />
                Añadir NIF
              </Button>
              {sucio && (
                <Button type="button" size="sm" onClick={submit} disabled={guardar.isPending}>
                  {guardar.isPending ? "Guardando…" : "Guardar"}
                </Button>
              )}
            </div>
          </>
        )}
      </div>
    </Panel>
  );
}
