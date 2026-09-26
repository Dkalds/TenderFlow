"use client";

/**
 * Los órganos de contratación de la cuenta: por los que avisa y los que suma
 * la ficha.
 *
 * El último no se puede quitar —una cuenta sin órganos no avisaría de nada, y
 * el servidor lo rechaza con 409—, así que con uno solo no se ofrece: para
 * dejar de seguir al cliente está «Dejar de seguir» en la cabecera.
 */

import * as React from "react";
import Link from "next/link";
import { Loader2, Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Panel, SectionTitle } from "@/components/console/panel";
import { useAnadirOrganos, useQuitarOrgano, type Cuenta } from "@/hooks/use-cuentas";

import { SelectorOrganos } from "../../_components/selector-organos";

function AnadirOrganosDialog({
  cuenta,
  open,
  onOpenChange,
}: {
  cuenta: Cuenta;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [organos, setOrganos] = React.useState<string[]>([]);
  const anadir = useAnadirOrganos();

  function cerrar(abierto: boolean) {
    if (!abierto) setOrganos([]);
    onOpenChange(abierto);
  }

  return (
    <Dialog open={open} onOpenChange={cerrar}>
      <DialogContent className="max-h-[calc(100vh-2rem)] w-[min(40rem,calc(100vw-2rem))] overflow-y-auto p-5">
        <DialogTitle>Añadir órganos a «{cuenta.nombre}»</DialogTitle>
        <DialogDescription className="mt-1">
          La cuenta avisará también de lo que publiquen y de sus contratos que venzan.
        </DialogDescription>
        <form
          className="mt-4 flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (organos.length === 0) return;
            anadir.mutate(
              { cuentaId: cuenta.id, organos },
              { onSuccess: () => cerrar(false) },
            );
          }}
        >
          <SelectorOrganos seleccionados={organos} onChange={setOrganos} cuentaId={cuenta.id} />
          <div className="flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" variant="ghost">
                Cancelar
              </Button>
            </DialogClose>
            <Button type="submit" disabled={organos.length === 0 || anadir.isPending}>
              {anadir.isPending && <Loader2 className="animate-spin" aria-hidden="true" />}
              Añadir {organos.length > 1 ? `${organos.length} órganos` : "órgano"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function OrganosCuenta({ cuenta, puedeEscribir }: { cuenta: Cuenta; puedeEscribir: boolean }) {
  const organos = cuenta.organos ?? [];
  const quitar = useQuitarOrgano();
  const [anadiendo, setAnadiendo] = React.useState(false);
  const sePuedeQuitar = puedeEscribir && organos.length > 1;

  return (
    <Panel>
      <SectionTitle
        aside={
          puedeEscribir ? (
            <Button variant="ghost" size="sm" onClick={() => setAnadiendo(true)}>
              <Plus aria-hidden="true" />
              Añadir
            </Button>
          ) : undefined
        }
      >
        {organos.length === 1 ? "Órgano de contratación" : `${organos.length} órganos de contratación`}
      </SectionTitle>
      <ul className="flex flex-col gap-1.5">
        {organos.map((organo) => (
          <li key={organo.id} className="flex items-start gap-2 text-sm">
            <Link
              href={`/mercado?vista=organos&organo_q=${encodeURIComponent(organo.organo_nombre)}`}
              className="min-w-0 flex-1 leading-tight hover:underline"
            >
              {organo.organo_nombre}
            </Link>
            {sePuedeQuitar && (
              <button
                type="button"
                onClick={() => quitar.mutate({ cuentaId: cuenta.id, cuentaOrganoId: organo.id })}
                disabled={quitar.isPending}
                className="grid h-6 w-6 flex-none place-items-center rounded text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50"
              >
                <X className="h-3.5 w-3.5" aria-hidden="true" />
                <span className="sr-only">Quitar {organo.organo_nombre} de la cuenta</span>
              </button>
            )}
          </li>
        ))}
      </ul>
      {puedeEscribir && (
        <AnadirOrganosDialog cuenta={cuenta} open={anadiendo} onOpenChange={setAnadiendo} />
      )}
    </Panel>
  );
}
