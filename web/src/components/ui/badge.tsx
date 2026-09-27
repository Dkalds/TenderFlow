import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

/**
 * Chip de estado o de categoría. Es un `<span>` que no se pulsa: sin hover, sin
 * foco, sin transición y sin sombra (el Badge de shadcn era un `div` con
 * `hover:bg-primary/80` y `focus:ring`, y además no podía ir dentro de un `<p>`).
 *
 * Todas las variantes de tono son el mismo dibujo: tinte al 10 %, borde al 30 %
 * y texto del tono. `neutral` es la de por defecto.
 *
 * Contraste: en el tema oscuro, `--destructive` sobre su propio tinte baja de
 * 4,5:1 (3,9:1 medido; el token ya está en 4,2:1 sobre la tarjeta, deuda
 * conocida de `contraste-tokens.test.ts`), así que `destructive` pierde el
 * relleno en oscuro y se queda en borde y texto.
 */
const badgeVariants = cva(
  "inline-flex items-center gap-1 whitespace-nowrap rounded-md border font-medium [&_svg]:size-3 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        neutral: "border-muted-foreground/20 bg-muted-foreground/10 text-muted-foreground",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        outline: "border-border text-foreground",
        success: "border-success/30 bg-success/10 text-success",
        warning: "border-warning/30 bg-warning/10 text-warning",
        info: "border-info/30 bg-info/10 text-info",
        destructive: "border-destructive/30 bg-destructive/10 text-destructive dark:bg-transparent",
        /**
         * @deprecated Era el primario macizo de shadcn. Ahora es el tinte
         * primario; elige el tono que corresponda (`success`, `info`…).
         */
        default: "border-primary/30 bg-primary/10 text-primary",
      },
      size: {
        /** 20 px de alto, 11 px: filas de tabla, cabeceras de lista. */
        sm: "h-5 px-1.5 text-tf-micro",
        /** 12 px: el de siempre. */
        md: "px-2 py-0.5 text-tf-meta",
      },
    },
    defaultVariants: {
      variant: "neutral",
      size: "md",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, size, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant, size }), className)} {...props} />
}

export { Badge, badgeVariants }
