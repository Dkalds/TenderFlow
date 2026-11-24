"use client"

import * as React from "react"
import { Check } from "lucide-react"
import { cn } from "@/lib/utils"

type CheckboxProps = Omit<React.ComponentProps<"button">, "value" | "defaultChecked" | "type"> & {
  checked?: boolean
  defaultChecked?: boolean
  onCheckedChange?: (checked: boolean) => void
}

/**
 * Casilla de dos estados con el marcado y el teclado de la de Radix
 * (`button[role=checkbox]`, `aria-checked`, `data-state`; Espacio marca y
 * Intro no), sin su paquete: era lo único de su tamaño en el marco de
 * /detalle que no era contenido de la tabla (~4,5 KB por encima del objetivo).
 * Es un botón y no un `<input>` porque las dianas táctiles (`diana-tactil`,
 * el `::after` de /detalle) y los selectores `[role=checkbox]` de la tabla
 * necesitan un elemento que pinte pseudo-elementos.
 */
function Checkbox({
  className,
  checked,
  defaultChecked = false,
  onCheckedChange,
  onClick,
  onKeyDown,
  disabled,
  ...props
}: CheckboxProps) {
  const [interno, setInterno] = React.useState(defaultChecked)
  const marcado = checked ?? interno

  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={marcado}
      data-state={marcado ? "checked" : "unchecked"}
      data-disabled={disabled ? "" : undefined}
      disabled={disabled}
      className={cn(
        "peer h-4 w-4 shrink-0 rounded-sm border border-primary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground",
        className
      )}
      onKeyDown={(event) => {
        onKeyDown?.(event)
        // WAI-ARIA: una casilla se marca con Espacio; Intro envía el formulario.
        if (event.key === "Enter") event.preventDefault()
      }}
      onClick={(event) => {
        onClick?.(event)
        if (event.defaultPrevented) return
        if (checked === undefined) setInterno(!marcado)
        onCheckedChange?.(!marcado)
      }}
      {...props}
    >
      {marcado ? (
        <span className="flex items-center justify-center text-current">
          <Check className="h-4 w-4" aria-hidden="true" />
        </span>
      ) : null}
    </button>
  )
}

export { Checkbox }
