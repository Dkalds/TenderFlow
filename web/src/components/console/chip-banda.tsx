import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Banda de puntuación de una licitación (Caliente, Atractiva, Tibia, Descarte)
 * como chip: la firma del producto, dibujada una sola vez.
 *
 * Antes cada pantalla la traducía a su manera: el inspector de Detalle a las
 * variantes de `Badge` (Caliente = `destructive`, con iconos del tiempo), el
 * del Radar a un chip con `style` inline sobre `--score-*`, y la fila del Radar
 * a un rótulo mono de 8 px. Aquí se lee solo de los tokens `--score-*`, que son
 * los mismos que colorean la cifra del score.
 *
 * Solo pinta lo que da la API (la banda): ADR-014.
 *
 * Contraste: el texto va en el color de la banda sobre su tinte al 10 %. En el
 * tema oscuro, `--score-hot` sobre su propio tinte baja de 4,5:1 (4,16:1
 * medido), así que Caliente pierde el relleno en oscuro y se queda en borde y
 * texto (4,51:1). El resto de bandas pasa con relleno en los dos temas.
 */

/* Cadenas completas y estáticas: el JIT de Tailwind solo ve lo que está escrito. */
const CLASE_BANDA = {
  Caliente:
    "border-[hsl(var(--score-hot)/0.3)] bg-[hsl(var(--score-hot)/0.1)] text-[hsl(var(--score-hot))] dark:bg-transparent",
  Atractiva: "border-[hsl(var(--score-warm)/0.3)] bg-[hsl(var(--score-warm)/0.1)] text-[hsl(var(--score-warm))]",
  Tibia: "border-[hsl(var(--score-cold)/0.3)] bg-[hsl(var(--score-cold)/0.1)] text-[hsl(var(--score-cold))]",
  Descarte: "border-[hsl(var(--score-skip)/0.3)] bg-[hsl(var(--score-skip)/0.1)] text-[hsl(var(--score-skip))]",
} as const;

export type BandaPuntuacion = keyof typeof CLASE_BANDA;

/** ¿Es `valor` una de las cuatro bandas que devuelve la API? */
export function esBandaConocida(valor: string | null | undefined): valor is BandaPuntuacion {
  return valor != null && Object.prototype.hasOwnProperty.call(CLASE_BANDA, valor);
}

export interface ChipBandaProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** La banda tal como la da la API. Sin banda, «Sin puntuar». */
  banda: string | null | undefined;
  /** `sm` (20 px, filas y tablas) o `md` (22 px, cabeceras de ficha). */
  size?: "sm" | "md";
}

export function ChipBanda({ banda, size = "sm", className, ...props }: ChipBandaProps) {
  const clase = esBandaConocida(banda) ? CLASE_BANDA[banda] : CLASE_BANDA.Descarte;
  return (
    <span
      data-slot="chip-banda"
      {...props}
      className={cn(
        "inline-flex items-center rounded-md border font-semibold whitespace-nowrap",
        size === "md" ? "text-tf-meta h-5.5 px-2" : "text-tf-micro h-5 px-1.5",
        clase,
        className,
      )}
    >
      {banda || "Sin puntuar"}
    </span>
  );
}
