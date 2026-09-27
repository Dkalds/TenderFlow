"use client";

/**
 * De dónde sale la fecha de fin de un contrato de la cartera.
 *
 * Vivía dentro de `cartera-view.tsx`; sale aquí porque la tabla y el inspector
 * enseñan la misma fecha y tienen que decir lo mismo de ella (ADR-014: una
 * fecha estimada por duración no se lee igual que una publicada).
 *
 * Es un `button` y no un `span` con `title` porque el `title` nativo no se
 * dispara con teclado: la explicación es dato, no decoración, y tiene que
 * alcanzarse tabulando.
 */
import { badgeVariants } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { origenFin } from "@/lib/cartera";

export function OrigenFin({ origen }: { origen: string | null | undefined }) {
  const info = origenFin(origen);
  if (!info) return null;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={`Fecha de fin ${info.texto}: ${info.explicacion}`}
          className={cn(badgeVariants({ size: "sm" }), "tf-pressable ml-1.5 hover:text-foreground")}
        >
          {info.texto}
        </button>
      </TooltipTrigger>
      <TooltipContent>{info.explicacion}</TooltipContent>
    </Tooltip>
  );
}
