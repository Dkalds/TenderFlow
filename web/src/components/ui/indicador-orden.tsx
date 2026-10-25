import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Flecha de orden de una cabecera de columna. `aria-hidden`: el estado de orden
 * lo anuncia el `aria-sort` del `<th>`, no el icono.
 *
 * La columna activa enseña su sentido (`ArrowUp`/`ArrowDown`) en el color del
 * texto. Las demás no enseñan nada en reposo —«↑↓» detrás de las once
 * cabeceras a la vez era ruido— y la doble flecha aparece al pasar el ratón o
 * al enfocar la cabecera (la cabecera lleva `group`). En táctil, sin hover, se
 * queda visible y tenue: si no, nada diría que la columna se puede ordenar.
 *
 * Vive fuera de `data-table.tsx` por el First Load: las tablas hechas a mano
 * (Detalle, el Resumen, Mercado, Competencia) solo usan esta flecha, pero un
 * módulo entra entero en el bundle de quien importa cualquiera de sus exports
 * (`web/AGENTS.md`), y aquél registra las features de TanStack Table al
 * cargarse. Medido el 2026-10-25: importar la flecha desde allí metía 36 KB de
 * `@tanstack/table-core` en /resumen y 41 KB en /detalle.
 */
export function IndicadorOrden({
  direccion,
  className,
}: {
  direccion: "asc" | "desc" | false | null | undefined;
  className?: string;
}) {
  if (direccion === "asc") {
    return <ArrowUp className={cn("h-3 w-3 flex-none text-foreground", className)} aria-hidden="true" />;
  }
  if (direccion === "desc") {
    return <ArrowDown className={cn("h-3 w-3 flex-none text-foreground", className)} aria-hidden="true" />;
  }
  return (
    <ArrowUpDown
      className={cn(
        "h-3 w-3 flex-none opacity-0 transition-opacity group-hover:opacity-60 group-focus-visible:opacity-60 pointer-coarse:opacity-40",
        className,
      )}
      aria-hidden="true"
    />
  );
}
