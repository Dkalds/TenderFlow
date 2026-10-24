"use client";

/**
 * Confirmación de lo que abre o cierra el acceso: conceder un dominio, revocar
 * una concesión y volver a conceder una revocada.
 *
 * Un clic bastaba para abrir el dominio entero de una empresa, y con la fila
 * delante es fácil acertar al botón de al lado. Por eso el diálogo dice **a
 * quién afecta** y, cuando la acción escribe a alguien, que le llegará un
 * correo: conceder (y volver a conceder) avisa siempre a quien pidió el acceso.
 */

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import type { AccessGrant } from "../../_hooks/use-solicitudes-acceso";

export type AccionDeAcceso =
  | { tipo: "conceder-dominio"; solicitudId: number; email: string; dominio: string }
  | { tipo: "revocar"; grantId: number; kind: AccessGrant["kind"]; value: string }
  | {
      tipo: "volver-a-conceder";
      solicitudId: number;
      kind: AccessGrant["kind"];
      value: string;
      /** A quién se le escribe: el de la solicitud que reactiva la concesión. */
      email: string;
    };

interface Textos {
  titulo: string;
  descripcion: string;
  boton: string;
  destructiva: boolean;
}

function textosDe(accion: AccionDeAcceso): Textos {
  switch (accion.tipo) {
    case "conceder-dominio":
      return {
        titulo: `Conceder el dominio ${accion.dominio}`,
        descripcion: `Cualquier cuenta @${accion.dominio} podrá iniciar sesión, no solo ${accion.email}. Se avisará por correo a ${accion.email}.`,
        boton: "Conceder dominio",
        destructiva: false,
      };
    case "revocar":
      return {
        titulo: `Revocar el acceso de ${accion.value}`,
        descripcion:
          accion.kind === "domain"
            ? `Las cuentas @${accion.value} que entraban por este acceso no podrán iniciar sesión de nuevo. Las sesiones abiertas no se cierran.`
            : `${accion.value} no podrá iniciar sesión de nuevo. Las sesiones abiertas no se cierran.`,
        boton: "Revocar",
        destructiva: true,
      };
    case "volver-a-conceder":
      return {
        titulo: `Volver a conceder el acceso a ${accion.value}`,
        descripcion:
          (accion.kind === "domain"
            ? `Cualquier cuenta @${accion.value} podrá iniciar sesión otra vez. `
            : `${accion.value} podrá iniciar sesión otra vez. `) + `${accion.email} recibirá un correo avisándole.`,
        boton: "Volver a conceder",
        destructiva: false,
      };
  }
}

export interface ConfirmarConcesionProps {
  /** Lo que espera confirmación; `null` = diálogo cerrado. */
  accion: AccionDeAcceso | null;
  ocupado: boolean;
  onCancelar: () => void;
  onConfirmar: (accion: AccionDeAcceso) => void;
}

export function ConfirmarConcesion({ accion, ocupado, onCancelar, onConfirmar }: ConfirmarConcesionProps) {
  if (!accion) return null;
  const { titulo, descripcion, boton, destructiva } = textosDe(accion);
  return (
    <Dialog open onOpenChange={(abierto) => (abierto ? undefined : onCancelar())}>
      <DialogContent className="w-[min(30rem,calc(100vw-2rem))] p-5">
        <DialogTitle>{titulo}</DialogTitle>
        <DialogDescription className="mt-1 mb-4">{descripcion}</DialogDescription>
        <div className="flex items-center justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onCancelar}>
            Cancelar
          </Button>
          <Button
            size="sm"
            variant={destructiva ? "destructive" : "default"}
            disabled={ocupado}
            onClick={() => onConfirmar(accion)}
          >
            {boton}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
