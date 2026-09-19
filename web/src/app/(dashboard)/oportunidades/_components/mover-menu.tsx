"use client";

import { EllipsisVertical } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Pursuit } from "@/hooks/use-pursuits";
import { FASES, faseDe, type FaseKey } from "../_lib/fases";
import { bloqueoDeFase, resultadosPermitidos } from "../_lib/flujo";

/**
 * La vía de teclado para mover una tarjeta.
 *
 * Arrastrar y soltar es cómodo con ratón y no existe sin él: `dragstart` no lo
 * emite el teclado y un lector de pantalla no tiene forma de expresar «suelta
 * esto en la tercera columna». Sin este menú el tablero sería una pantalla que
 * sólo se puede usar apuntando, así que **no es opcional**: cada tarjeta
 * arrastrable lo lleva.
 *
 * Lista las seis fases, con las que el flujo no permite deshabilitadas: así se
 * ve el orden entero y cuál es el único paso posible. Cuando cerrar solo puede
 * ser retirarla, la opción lo dice.
 *
 * El nombre accesible incluye el título de la oportunidad porque en una columna
 * hay varios de estos botones y «Mover de fase» repetido ocho veces no dice
 * cuál es cuál.
 */
export function MoverMenu({
  pursuit,
  onMover,
}: {
  pursuit: Pursuit;
  onMover: (destino: FaseKey) => void;
}) {
  const actual = faseDe(pursuit.status);
  const titulo = pursuit.tender_title ?? `Licitación ${pursuit.licitacion_id}`;
  const soloRetirar = resultadosPermitidos(pursuit).every((resultado) => resultado === "withdrawn");
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={`Mover «${titulo}» de fase`}
        className="text-muted-foreground hover:text-foreground hover:bg-accent focus-visible:ring-ring grid h-6 w-6 flex-none place-items-center rounded-md transition-colors focus-visible:ring-1"
      >
        <EllipsisVertical className="h-3.5 w-3.5" aria-hidden="true" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {FASES.map((fase) => (
          <DropdownMenuItem
            key={fase.key}
            disabled={fase.key === actual || bloqueoDeFase(pursuit, fase.key) !== null}
            onSelect={() => onMover(fase.key)}
          >
            {fase.key === "cerrada" ? (soloRetirar ? "Retirar…" : "Cerrar…") : fase.titulo}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
