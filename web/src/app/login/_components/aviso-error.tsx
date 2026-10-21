"use client";

/**
 * Error general de la puerta, con lo que se puede hacer con él cuando hay algo
 * que hacer: pedir el acceso que falta o pedir otro enlace de activación.
 *
 * El `id` es el destino de los `aria-describedby` de los campos (`login-error`
 * en el formulario): el lector de pantalla lee el motivo, y la salida, al
 * volver a cada uno. El aviso lleva `role="alert"` (tono `danger`), así que se
 * anuncia al aparecer sin mover el foco.
 */

import { Aviso } from "@/components/console/aviso";
import { solicitarAccesoHref } from "@/lib/contacto";
import type { AccionError } from "../_hooks/use-login-form";

const ENLACE =
  "text-foreground focus-visible:ring-ring rounded-sm font-medium underline underline-offset-4 focus-visible:ring-2 focus-visible:outline-none";

export function AvisoError({
  id,
  texto,
  accion,
  onPedirOtroEnlace,
  disabled,
}: {
  id: string;
  texto: string;
  accion: AccionError | null;
  /** Lo que hace «Recibir otro enlace» (`accion === "reenviar_enlace"`). */
  onPedirOtroEnlace?: () => void;
  disabled?: boolean;
}) {
  return (
    <div id={id} className="animate-in fade-in-0 slide-in-from-bottom-2">
      <Aviso tone="danger">
        {texto}
        {accion === "solicitar_acceso" && (
          <>
            {" "}
            <a href={solicitarAccesoHref()} className={ENLACE}>
              Solicita acceso
            </a>
          </>
        )}
        {accion === "reenviar_enlace" && onPedirOtroEnlace && (
          <>
            {" "}
            <button type="button" className={ENLACE} onClick={onPedirOtroEnlace} disabled={disabled}>
              Recibir otro enlace
            </button>
          </>
        )}
      </Aviso>
    </div>
  );
}
