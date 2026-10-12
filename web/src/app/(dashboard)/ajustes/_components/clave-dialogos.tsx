"use client";

/**
 * Las dos confirmaciones de una clave: rotarla y revocarla.
 *
 * Los dos diálogos montan su contenido al abrirse, así que cada apertura
 * empieza sin el error de la anterior. Los fallos se pintan dentro, junto al
 * botón que los provocó; la sesión antigua ofrece volver a entrar.
 */

import * as React from "react";
import { Aviso, Segmented } from "@/components/console/panel";
import { AvisoReautenticacion } from "@/components/console/aviso-reautenticacion";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { type MiClave, useRevocarClave, useRotarClave } from "@/hooks/use-ajustes";
import { getErrorMessage } from "@/lib/query-feedback";
import { pideReautenticacion } from "@/lib/reautenticacion";
import { formatDateTime } from "@/lib/utils";

/** Días que la clave anterior sigue valiendo tras rotar. La API acepta de 0 a 30. */
const GRACIAS = [
  { value: "0", label: "Ninguno" },
  { value: "1", label: "Un día" },
  { value: "7", label: "Una semana" },
  { value: "30", label: "Un mes" },
] as const;
type Gracia = (typeof GRACIAS)[number]["value"];

function ErrorDeClave({ error, accion }: { error: unknown; accion: string }) {
  if (pideReautenticacion(error)) return <AvisoReautenticacion accion={accion} />;
  return <Aviso tone="danger">{getErrorMessage(error, "accion")}</Aviso>;
}

const nombreDe = (clave: MiClave) => clave.name || `Clave ${clave.id}`;

export function RotarClaveDialog({
  clave,
  open,
  onOpenChange,
  onRotada,
}: {
  clave: MiClave;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** El token nuevo y lo que hay que saber de la anterior. */
  onRotada: (token: string, nota: string) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[min(32rem,calc(100vw-2rem))] p-5">
        <DialogTitle>Rotar «{nombreDe(clave)}»</DialogTitle>
        <DialogDescription className="mt-1">
          Se crea otra clave con los mismos permisos. Elige cuánto tiempo sigue valiendo la anterior, para cambiarla
          en tu integración sin cortes.
        </DialogDescription>
        <FormularioRotar clave={clave} onRotada={onRotada} onHecho={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function FormularioRotar({
  clave,
  onRotada,
  onHecho,
}: {
  clave: MiClave;
  onRotada: (token: string, nota: string) => void;
  onHecho: () => void;
}) {
  const rotar = useRotarClave();
  const [gracia, setGracia] = React.useState<Gracia>("7");

  const confirmar = () => {
    const diasDeGracia = Number(gracia);
    rotar.mutate(
      { keyId: clave.id, diasDeGracia },
      {
        onSuccess: (rotada) => {
          // La nota sale de lo que se pidió, no del reloj de quien mira: con
          // cero días la anterior caduca en el acto aunque su fecha sea «hoy».
          onRotada(
            rotada.new_token,
            diasDeGracia === 0
              ? "La anterior ya no vale."
              : `La anterior sigue valiendo hasta el ${formatDateTime(new Date(rotada.old_key_expires_at))}.`,
          );
          onHecho();
        },
      },
    );
  };

  return (
    <div className="mt-4 flex flex-col gap-4">
      <div>
        <p className="mb-1.5 text-tf-meta font-medium">Margen para la clave anterior</p>
        <Segmented
          aria-label="Margen para la clave anterior"
          value={gracia}
          onChange={setGracia}
          options={GRACIAS}
        />
      </div>
      {rotar.error ? <ErrorDeClave error={rotar.error} accion="rotar la clave" /> : null}
      <div className="flex justify-end gap-2">
        <DialogClose asChild>
          <Button type="button" variant="ghost" size="sm">
            Cancelar
          </Button>
        </DialogClose>
        <Button type="button" size="sm" disabled={rotar.isPending} onClick={confirmar}>
          Rotar clave
        </Button>
      </div>
    </div>
  );
}

export function RevocarClaveDialog({
  clave,
  open,
  onOpenChange,
}: {
  clave: MiClave;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[min(32rem,calc(100vw-2rem))] p-5">
        <DialogTitle>Revocar «{nombreDe(clave)}»</DialogTitle>
        <DialogDescription className="mt-1">
          Lo que use esta clave dejará de entrar al momento. No se puede deshacer: si vuelves a necesitarla, crea
          otra.
        </DialogDescription>
        <FormularioRevocar clave={clave} onHecho={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function FormularioRevocar({ clave, onHecho }: { clave: MiClave; onHecho: () => void }) {
  const revocar = useRevocarClave();
  return (
    <div className="mt-4 flex flex-col gap-4">
      {revocar.error ? <ErrorDeClave error={revocar.error} accion="revocar la clave" /> : null}
      <div className="flex justify-end gap-2">
        <DialogClose asChild>
          <Button type="button" variant="ghost" size="sm">
            Cancelar
          </Button>
        </DialogClose>
        <Button
          type="button"
          size="sm"
          variant="destructive"
          disabled={revocar.isPending}
          onClick={() => revocar.mutate(clave.id, { onSuccess: onHecho })}
        >
          Revocar clave
        </Button>
      </div>
    </div>
  );
}
