"use client"

import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

/**
 * Botón de la app. Plano (sin la sombra de shadcn: la elevación es de las capas
 * flotantes, no de los controles) y con la talla de la consola en `sm`.
 *
 * Tallas:
 * - `sm`: la de la consola. 28 px desde `md` y 32 px en móvil (diana para el
 *   pulgar), texto a 12 px e iconos a 14 px. Es la que va en barras de
 *   herramientas, cabeceras de panel y acciones de fila.
 * - `default`: 36 px, texto a 14 px, iconos a 16 px. Formularios y diálogos.
 * - `lg`: 40 px. Llamadas a la acción de las pantallas de acceso.
 * - `icon` (36 px) e `icon-sm` (28 px en escritorio): solo icono; llevan
 *   `aria-label`.
 *
 * El icono mide lo que pide la talla: `[&_svg]:size-*` va en cada talla y pisa
 * el `h-*`/`w-*` que traiga el icono, así que dentro de un `Button` el icono no
 * lleva clases de tamaño ni `mr-2` (el hueco lo pone `gap`).
 *
 * Pulsación: `scale` a 0,97 que sí anima (Tailwind 4 escribe `scale:`, no
 * `transform:`, así que la transición tiene que nombrar `scale`). Con
 * `prefers-reduced-motion` no escala.
 */
const variantesBoton = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-[background-color,color,border-color,scale] duration-150 ease-out active:scale-[0.97] motion-reduce:active:scale-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        outline: "border border-input bg-card hover:bg-accent hover:text-accent-foreground",
        secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2 [&_svg]:size-4",
        sm: "h-8 gap-1.5 px-2.5 text-tf-meta md:h-7 [&_svg]:size-3.5",
        lg: "h-10 px-8 [&_svg]:size-4",
        icon: "h-9 w-9 [&_svg]:size-4",
        "icon-sm": "size-8 md:size-7 [&_svg]:size-3.5",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

type ButtonVariantProps = VariantProps<typeof variantesBoton>

/**
 * Clases de un botón, para lo que no puede ser un `Button` (el disparador de un
 * menú, un `Link`). Pasan por `cn()`, así que la talla pisa de verdad el
 * tamaño de letra base.
 */
function buttonVariants(props?: Parameters<typeof variantesBoton>[0]): string {
  return cn(variantesBoton(props))
}

export interface ButtonProps
  extends React.ComponentProps<"button">,
    ButtonVariantProps {
  asChild?: boolean
}

function Button({ className, variant, size, asChild = false, ...props }: ButtonProps) {
  // `asChild` renders the button's styling/behavior onto its child (e.g. a
  // Next `<Link>`) instead of wrapping it in a real `<button>`, which
  // produces invalid `<button><a>...` nesting and breaks link semantics
  // (right-click "open in new tab", screen reader link role, etc.).
  const Comp = asChild ? Slot : "button"
  return <Comp className={buttonVariants({ variant, size, className })} {...props} />
}

export { Button, buttonVariants }
export type { ButtonVariantProps }
