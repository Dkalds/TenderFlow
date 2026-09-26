"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useCrearCuenta } from "@/hooks/use-cuentas";

import { SelectorOrganos } from "./selector-organos";

/**
 * Alta de una cuenta: un cliente y sus órganos de contratación.
 *
 * El nombre es opcional y por defecto el del primer órgano, que para un
 * cliente de un solo órgano es el nombre natural. Para uno de varios —el
 * Ayuntamiento de Madrid y sus seis órganos— es donde el equipo le pone el
 * nombre con el que lo reconoce.
 */
export function NuevaCuentaDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [organos, setOrganos] = React.useState<string[]>([]);
  const [nombre, setNombre] = React.useState("");
  const [nota, setNota] = React.useState("");
  const crear = useCrearCuenta();
  const id = React.useId();

  function cerrar(abierto: boolean) {
    if (!abierto) {
      setOrganos([]);
      setNombre("");
      setNota("");
    }
    onOpenChange(abierto);
  }

  return (
    <Dialog open={open} onOpenChange={cerrar}>
      <DialogContent className="max-h-[calc(100vh-2rem)] w-[min(40rem,calc(100vw-2rem))] overflow-y-auto p-5">
        <DialogTitle>Nueva cuenta</DialogTitle>
        <DialogDescription className="mt-1">
          Un cliente y sus órganos de contratación. Todo el equipo recibirá en la campana sus
          publicaciones nuevas y los contratos que entren en sus últimos seis meses.
        </DialogDescription>

        <form
          className="mt-4 flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (organos.length === 0) return;
            crear.mutate({ nombre, organos, nota }, { onSuccess: () => cerrar(false) });
          }}
        >
          <SelectorOrganos seleccionados={organos} onChange={setOrganos} />

          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${id}-nombre`} className="text-sm font-medium">
              Nombre de la cuenta <span className="font-normal text-muted-foreground">(opcional)</span>
            </label>
            <Input
              id={`${id}-nombre`}
              value={nombre}
              onChange={(event) => setNombre(event.target.value)}
              placeholder={organos[0] ?? "Ayuntamiento de…"}
              maxLength={500}
              aria-describedby={`${id}-nombre-pista`}
            />
            <p id={`${id}-nombre-pista`} className="text-xs text-muted-foreground">
              Si lo dejas vacío, la cuenta se llamará como su primer órgano.
            </p>
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${id}-nota`} className="text-sm font-medium">
              Nota <span className="font-normal text-muted-foreground">(opcional)</span>
            </label>
            <Textarea
              id={`${id}-nota`}
              value={nota}
              onChange={(event) => setNota(event.target.value)}
              placeholder="Renueva el mantenimiento en marzo; contacto: jefa de servicio de TI"
              maxLength={2000}
              rows={2}
            />
          </div>

          <div className="flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" variant="ghost">
                Cancelar
              </Button>
            </DialogClose>
            <Button type="submit" disabled={organos.length === 0 || crear.isPending}>
              {crear.isPending && <Loader2 className="animate-spin" aria-hidden="true" />}
              Crear cuenta
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
