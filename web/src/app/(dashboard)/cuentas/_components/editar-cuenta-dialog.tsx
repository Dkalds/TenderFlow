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
import { useEditarCuenta, type Cuenta, type EdicionDeCuenta } from "@/hooks/use-cuentas";

/**
 * Renombrar la cuenta y cambiar su nota.
 *
 * Sólo viaja lo que cambió. Mandar siempre los dos campos convertiría «no toqué
 * la nota» en «pon esta nota», y un compañero que la editó mientras tanto
 * perdería su cambio sin saberlo. Vaciar la nota la borra (`nota: null`).
 */
export function EditarCuentaDialog({
  cuenta,
  open,
  onOpenChange,
}: {
  cuenta: Cuenta;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[min(32rem,calc(100vw-2rem))] p-5">
        <DialogTitle>Editar cuenta</DialogTitle>
        <DialogDescription className="mt-1">
          El nombre y la nota son del equipo: los ve y los puede cambiar cualquier miembro.
        </DialogDescription>
        {/* El contenido del diálogo se monta al abrir, así que el formulario
            arranca siempre con lo que la cuenta tiene ahora: entre dos
            aperturas otro miembro pudo cambiarla. */}
        <FormularioEdicion cuenta={cuenta} onHecho={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function FormularioEdicion({ cuenta, onHecho }: { cuenta: Cuenta; onHecho: () => void }) {
  const [nombre, setNombre] = React.useState(cuenta.nombre);
  const [nota, setNota] = React.useState(cuenta.nota ?? "");
  const editar = useEditarCuenta();
  const id = React.useId();

  const cambios: EdicionDeCuenta = { cuentaId: cuenta.id };
  if (nombre.trim() && nombre.trim() !== cuenta.nombre) cambios.nombre = nombre.trim();
  if (nota.trim() !== (cuenta.nota ?? "")) cambios.nota = nota.trim() || null;
  const hayCambios = "nombre" in cambios || "nota" in cambios;

  return (
    <form
      className="mt-4 flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!hayCambios) return onHecho();
        editar.mutate(cambios, { onSuccess: onHecho });
      }}
    >
      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${id}-nombre`} className="text-sm font-medium">
          Nombre de la cuenta
        </label>
        <Input
          id={`${id}-nombre`}
          value={nombre}
          onChange={(event) => setNombre(event.target.value)}
          maxLength={500}
          required
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${id}-nota`} className="text-sm font-medium">
          Nota
        </label>
        <Textarea
          id={`${id}-nota`}
          value={nota}
          onChange={(event) => setNota(event.target.value)}
          maxLength={2000}
          rows={3}
        />
      </div>
      <div className="flex justify-end gap-2">
        <DialogClose asChild>
          <Button type="button" variant="ghost">
            Cancelar
          </Button>
        </DialogClose>
        <Button type="submit" disabled={!nombre.trim() || editar.isPending}>
          {editar.isPending && <Loader2 className="animate-spin" aria-hidden="true" />}
          Guardar
        </Button>
      </div>
    </form>
  );
}
