/**
 * Los dibujos mínimos de Competencia: la barra de proporción, el ala de un
 * gráfico mariposa y la muestra de color de una leyenda.
 *
 * Son SVG con el ancho en el propio `rect`, sin `style` en línea, y sin
 * transición: es una medida, no algo que se mueva. Todos son decorativos para
 * el lector de pantalla (`aria-hidden`); la cifra va escrita al lado.
 */

import { cn } from "@/lib/utils";

const acotar = (pct: number) => Math.max(0, Math.min(100, pct));

/** Barra de proporción sobre su carril: cuánto de 100. */
export function BarraPct({
  pct,
  color = "hsl(var(--primary))",
  className,
}: {
  pct: number;
  color?: string;
  className?: string;
}) {
  return (
    <svg
      aria-hidden="true"
      className={cn("h-2 w-full overflow-hidden rounded-full", className)}
      viewBox="0 0 100 10"
      preserveAspectRatio="none"
    >
      <rect width="100" height="10" className="fill-muted" />
      <rect width={acotar(pct)} height="10" fill={color} />
    </svg>
  );
}

/** Un ala de la mariposa: crece desde el centro hacia su lado. */
export function Ala({ pct, lado, color }: { pct: number; lado: "izquierda" | "derecha"; color: string }) {
  const ancho = acotar(pct);
  return (
    <svg aria-hidden="true" className="h-3 w-full" viewBox="0 0 100 10" preserveAspectRatio="none">
      <rect x={lado === "izquierda" ? 100 - ancho : 0} y="0" width={ancho} height="10" fill={color} />
    </svg>
  );
}

/** La muestra de color de una entrada de leyenda. */
export function Muestra({ color, className }: { color: string; className?: string }) {
  return (
    <svg aria-hidden="true" className={cn("h-2.5 w-2.5 flex-none", className)} viewBox="0 0 10 10">
      <rect width="10" height="10" rx="2" fill={color} />
    </svg>
  );
}
