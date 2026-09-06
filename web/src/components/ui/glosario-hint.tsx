"use client"

import * as React from "react"
import { HelpCircle } from "lucide-react"

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { type EntradaGlosario, glosario } from "@/lib/glosario"
import { cn } from "@/lib/utils"

/**
 * F1.8 — el `?` que explica un término sin sacar al usuario de la pantalla.
 *
 * Por qué `Tooltip` y no `title=`
 * -------------------------------
 * `title=` no se abre con teclado, no lo anuncia ningún lector de pantalla de
 * forma fiable, y en móvil no existe. El criterio de aceptación pide
 * accesible por teclado y anunciado: `TooltipTrigger` es un `<button>` real,
 * entra en el orden de tabulación y Radix ata el contenido al trigger por
 * `aria-describedby`. El icono va `aria-hidden` y el nombre accesible lo pone
 * el `sr-only`, para que el lector diga «Qué es Adjudicada» y no «imagen».
 *
 * El enlace a `/metodologia` va dentro del tooltip y no es interactivo: un
 * tooltip que se cierra al mover el ratón hacia su enlace es un enlace que no
 * se puede pulsar. Se pinta como referencia («Más en Metodología») y la
 * navegación real la ofrece la página, que sí tiene sitio para ella.
 */
export interface GlosarioHintProps {
  /** Clave del glosario (`ADJ`, `baja`…). Ignorada si se pasa `entrada`. */
  termino?: string
  /**
   * Entrada ya resuelta. La usan procedimiento y tramitación, cuyo texto llega
   * de `GET /meta/filters` y no del diccionario local (invariante 3).
   */
  entrada?: EntradaGlosario
  className?: string
}

export function GlosarioHint({ termino, entrada, className }: GlosarioHintProps) {
  const definicion = entrada ?? glosario(termino)
  // Sin entrada no se pinta nada. Un `?` que al abrirse dice «sin definición»
  // gasta la atención del usuario para no darle nada.
  if (!definicion) return null

  return (
    <Tooltip>
      <TooltipTrigger
        type="button"
        className={cn(
          "inline-flex size-4 shrink-0 items-center justify-center rounded-full align-middle",
          "text-muted-foreground/70 transition-colors hover:text-foreground",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
          className
        )}
      >
        <HelpCircle className="size-3.5" aria-hidden="true" />
        <span className="sr-only">Qué es {definicion.termino}</span>
      </TooltipTrigger>
      <TooltipContent className="max-w-[18rem] text-pretty leading-relaxed">
        <p className="font-medium">{definicion.termino}</p>
        <p className="mt-1 text-muted-foreground">{definicion.definicion}</p>
        <p className="mt-1.5 text-[11px] text-muted-foreground/80">Más en Metodología</p>
      </TooltipContent>
    </Tooltip>
  )
}
