"use client";

import { Aviso } from "@/components/console/panel";
import { cn } from "@/lib/utils";
import { enumerar } from "./alcance";

/**
 * Aviso de ámbito parcial. Va pegado al panel que no aplica todos los chips,
 * no en la cabecera de la página: el problema es de ese panel y de ningún otro.
 *
 * `sujeto="activas"` es la variante de la tira de contexto, donde solo la
 * celda «Activas» sale del recuento parcial y sus vecinas aplican el ámbito
 * entero: avisar de «estas cifras» ahí señalaría siete celdas por una.
 */
export function AvisoAlcance({
  ignorados,
  sujeto = "cifras",
  className,
}: {
  ignorados: string[];
  sujeto?: "cifras" | "activas";
  className?: string;
}) {
  if (ignorados.length === 0) return null;
  return (
    <Aviso tone="warning" className={cn("mb-2.5", className)}>
      {sujeto === "activas"
        ? `«Activas» no aplica ${enumerar(ignorados)}: solo filtra por fecha, CCAA y tecnología.`
        : `Estas cifras no aplican ${enumerar(ignorados)}: solo filtran por fecha, CCAA y tecnología.`}
    </Aviso>
  );
}
