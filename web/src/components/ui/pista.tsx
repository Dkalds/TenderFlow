"use client"

import * as React from "react"

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

/**
 * El sustituto de `title=` para lo que **no es un control**: el texto truncado
 * de una celda, la casilla de un heatmap, el punto de «nueva».
 *
 * Por qué no un `TooltipTrigger` a secas
 * ---------------------------------------
 * `title=` no se ve con teclado ni en táctil y el lector lo anuncia a medias,
 * así que se retira (regla ESLint `deudaTitleNativo`, a cero). Pero el paso
 * obvio —envolver cada celda en un disparador focusable— mete **una parada de
 * tabulación por celda**: una tabla de 25 filas con dos textos truncados son 50
 * paradas más antes de llegar a la paginación, y un heatmap de un año, 365.
 *
 * Aquí el disparador es el propio elemento, que sigue sin ser focusable: el
 * tooltip aparece al pasar el puntero, que es exactamente lo que hacía el
 * `title`, y el orden de tabulación de la rejilla queda como estaba. Lo que el
 * teclado y el lector necesitan tiene que ir **en el texto**: el truncado es
 * CSS (el DOM conserva la cadena entera) y las casillas sin texto llevan su
 * dato como nombre accesible (`role="img"` + `aria-label`) en quien las pinta.
 *
 * Sin contenido no se monta nada: una celda vacía no abre un tooltip vacío.
 */
export function Pista({
  contenido,
  children,
  side,
}: {
  contenido: React.ReactNode
  /** Un único elemento; recibe los manejadores de puntero del disparador. */
  children: React.ReactElement
  side?: React.ComponentProps<typeof TooltipContent>["side"]
}) {
  if (contenido == null || contenido === "" || contenido === false) return children
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side={side} className="max-w-[22rem] text-pretty">
        {contenido}
      </TooltipContent>
    </Tooltip>
  )
}
