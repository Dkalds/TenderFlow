"use client";

import { PanelRight, Star, X } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { RadarTender } from "@/hooks/use-radar";

/**
 * Acciones de una fila: descartar, seguir, abrir oportunidad y —solo en la
 * franja en la que el inspector es un `Sheet`— abrir la ficha.
 *
 * Tienen columna propia y no se superponen a Importe ni a Plazo: al cambiar de
 * fila nada se mueve. En móvil están siempre visibles: revelarlas al
 * seleccionar es un gesto de hover, y en táctil convertiría descartar en dos
 * toques (uno para que aparezca el botón, otro para pulsarlo). Solo a partir de
 * `md` vuelven a depender de la fila activa.
 */
export function RadarAcciones({
  tender,
  isActive,
  inerte,
  followed,
  conFicha,
  onDismiss,
  onFollow,
  onOpenPursuit,
  onOpenFicha,
}: {
  tender: RadarTender;
  isActive: boolean;
  /** Verdadero solo donde el bloque está oculto (`md:opacity-0`) y no es activo. */
  inerte: boolean;
  followed: boolean;
  /** El inspector se abre como panel: entre `md` y `xl` hace falta un disparador. */
  conFicha: boolean;
  onDismiss: () => void;
  onFollow: () => void;
  onOpenPursuit: () => void;
  onOpenFicha: () => void;
}) {
  return (
    <div
      data-slot="radar-acciones"
      // `md:opacity-0` esconde el bloque pero lo deja en el orden
      // de tabulación: 23 filas inactivas × 3 botones eran 69
      // paradas invisibles, sin foco visible (WCAG 2.4.7). `inert`
      // los saca del foco y del árbol de accesibilidad, y solo
      // donde están ocultos: en la ficha móvil son visibles y
      // siguen siendo alcanzables.
      inert={inerte}
      className={cn(
        "flex items-center justify-end gap-2 border-t border-border/40 pt-2.5",
        "md:gap-1.5 md:border-t-0 md:pt-0",
        isActive
          ? "md:animate-in md:fade-in-0 md:slide-in-from-right-2 md:duration-[170ms]"
          : "md:pointer-events-none md:opacity-0",
      )}
    >
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={`Descartar ${tender.titulo}`}
            onClick={(event) => {
              event.stopPropagation();
              onDismiss();
            }}
            // 36×36 en móvil. Los 26 px de la consola cumplen el
            // mínimo de WCAG 2.5.8 (24×24) pero se fallan con el
            // pulgar, y aquí el error cuesta una señal descartada.
            className="tf-pressable grid h-9 w-9 place-items-center rounded-md border border-border/80 bg-card text-muted-foreground transition-colors duration-140 ease-out hover:border-destructive/50 hover:text-destructive md:h-6.5 md:w-6.5"
          >
            <X className="h-4 w-4 md:h-3 md:w-3" aria-hidden="true" />
          </button>
        </TooltipTrigger>
        <TooltipContent>Descartar · X</TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={followed ? `Dejar de seguir ${tender.titulo}` : `Seguir ${tender.titulo}`}
            aria-pressed={followed}
            onClick={(event) => {
              event.stopPropagation();
              onFollow();
            }}
            className={cn(
              "tf-pressable grid h-9 w-9 place-items-center rounded-md border transition-colors duration-140 ease-out md:h-6.5 md:w-6.5",
              followed
                ? "border-primary/50 bg-primary/16 text-primary"
                : "border-border/80 bg-card text-muted-foreground hover:text-foreground",
            )}
          >
            <Star
              className={cn("h-4 w-4 md:h-3 md:w-3", followed && "fill-current")}
              aria-hidden="true"
            />
          </button>
        </TooltipTrigger>
        <TooltipContent>Seguir · S</TooltipContent>
      </Tooltip>
      {conFicha && (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label={`Ver ficha de ${tender.titulo}`}
              onClick={(event) => {
                event.stopPropagation();
                onOpenFicha();
              }}
              className="tf-pressable grid h-9 w-9 place-items-center rounded-md border border-border/80 bg-card text-muted-foreground transition-colors duration-140 ease-out hover:text-foreground md:h-6.5 md:w-6.5"
            >
              <PanelRight className="h-4 w-4 md:h-3 md:w-3" aria-hidden="true" />
            </button>
          </TooltipTrigger>
          <TooltipContent>Ver ficha</TooltipContent>
        </Tooltip>
      )}
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              onOpenPursuit();
            }}
            // En móvil ocupa el resto de la línea: es la acción
            // que se busca, y el borde derecho es donde cae el
            // pulgar. En la tabla vuelve a su ancho de contenido.
            className="tf-pressable h-9 flex-1 whitespace-nowrap rounded-md border border-primary/35 bg-primary/14 px-2.5 text-[12px] font-semibold text-primary transition-colors duration-140 ease-out hover:bg-primary/24 md:h-6.5 md:flex-none md:text-[11px]"
          >
            Abrir
          </button>
        </TooltipTrigger>
        <TooltipContent>Abrir oportunidad · ⏎</TooltipContent>
      </Tooltip>
    </div>
  );
}
