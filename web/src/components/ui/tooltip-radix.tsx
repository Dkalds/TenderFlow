"use client"

import * as React from "react"
import * as TooltipPrimitive from "@radix-ui/react-tooltip"
import { cn } from "@/lib/utils"

/**
 * El tooltip real, con Radix y su popper (floating-ui). No se importa de forma
 * estática desde ningún sitio: lo pide `tooltip.tsx` cuando el navegador queda
 * ocioso o al acercarte a un disparador, para que no viaje en el First Load.
 *
 * Cada raíz lleva su propio `Provider` de Radix: el `TooltipProvider` de la
 * casa no puede montar el de Radix sin meterlo en la carga inicial, y cambiarlo
 * de sitio al llegar volvería a montar el dashboard entero. El «una vez que un
 * tooltip se ha visto, los vecinos abren sin esperar» lo lleva `tooltip.tsx`
 * pasando `delayDuration` a 0 mientras dura la ventana de `skipDelayDuration`.
 */
export function Raiz({
  delayDuration,
  skipDelayDuration,
  disableHoverableContent,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Root> & { skipDelayDuration: number }) {
  return (
    <TooltipPrimitive.Provider
      delayDuration={delayDuration}
      skipDelayDuration={skipDelayDuration}
      disableHoverableContent={disableHoverableContent}
    >
      <TooltipPrimitive.Root delayDuration={delayDuration} {...props} />
    </TooltipPrimitive.Provider>
  )
}

export const Disparador = TooltipPrimitive.Trigger

export function Contenido({
  className,
  sideOffset = 4,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Content>) {
  return (
    <TooltipPrimitive.Content
      sideOffset={sideOffset}
      className={cn(
        "z-50 overflow-hidden rounded-md border border-border bg-popover px-2.5 py-1.5 text-tf-meta text-popover-foreground shadow-md",
        // Scale from the trigger, not center (apple-design §7 / emil-design-eng).
        "origin-[var(--radix-tooltip-content-transform-origin)]",
        "data-[state=delayed-open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=delayed-open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=delayed-open]:zoom-in-95",
        className
      )}
      {...props}
    />
  )
}
