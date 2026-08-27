"use client";

import { AlertTriangle } from "lucide-react";
import { enumerar } from "./alcance";

/**
 * Aviso de ámbito parcial. Va pegado al panel que no aplica todos los chips,
 * no en la cabecera de la página: el problema es de ese panel y de ningún otro.
 */
export function AvisoAlcance({ ignorados }: { ignorados: string[] }) {
  if (ignorados.length === 0) return null;
  return (
    <p
      role="status"
      className="mb-2.5 flex items-start gap-1.5 rounded-lg border border-[hsl(var(--warning)/0.28)] bg-[hsl(var(--warning)/0.08)] px-2.5 py-1.5 text-[10.5px] leading-[1.45] text-[hsl(var(--warning))]"
    >
      <AlertTriangle className="mt-px h-3 w-3 flex-none" aria-hidden="true" />
      <span>
        Estas cifras no aplican {enumerar(ignorados)}: el endpoint sólo filtra por fecha, CCAA y
        tecnología.
      </span>
    </p>
  );
}
