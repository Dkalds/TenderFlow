import * as React from "react"
import { cn } from "@/lib/utils"

/**
 * Vocabulario de tarjeta **anterior** al de la consola. Congelado.
 *
 * En la superficie convivían dos vocabularios sin que ninguno estuviera marcado
 * como el saliente: éste y el de `components/console/panel.tsx` (`Panel`,
 * `PanelTitle`, `PanelTabs`, `PanelError`, `PanelEmpty`, `StatStrip`…). Con los
 * dos exportados y ninguno deprecado en código, cada pantalla nueva elegía por
 * lo que hubiera copiado su autor y la consola derivaba: dos cabeceras
 * distintas, dos vacíos distintos y dos alturas de estado de carga para la
 * misma clase de bloque.
 *
 * Gana el de la consola, porque hace cosas que éste no puede hacer: fija los
 * tres estados —carga, error y vacío— al **mismo alto que el contenido real**,
 * para que la página no salte al cargar, y arrastra las reglas del sistema de
 * gráficos (color de serie por índice, «Otros» en `chart-8`, nunca dos ejes Y
 * en un panel). `Card` es un `div` con borde: no sabe nada de eso.
 *
 * Este módulo NO se borra ni se migra de golpe. Lo importan decenas de ficheros
 * y un big-bang de esa talla es una regresión visual esperando a ocurrir; el
 * objetivo declarado es **parar la deriva, no reescribir la consola**. Lo que
 * corta la deriva es la regla `no-restricted-imports` de `eslint.config.mjs`:
 * prohíbe importar este módulo salvo en la allowlist de los ficheros que ya lo
 * usaban, y esa allowlist solo puede encoger. Para código nuevo —y al reescribir
 * uno de los de la allowlist— usá `@/components/console/panel`.
 *
 * @deprecated Usá `Panel` / `PanelTitle` de `@/components/console/panel`.
 */

/** @deprecated Usá `Panel` de `@/components/console/panel`. */
const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      data-slot="card"
      // Panel de consola, no tarjeta elevada: borde tenue, superficie mate y
      // sin sombra. La elevación separaba cada bloque del siguiente y en una
      // pantalla densa eso es ruido — el borde ya delimita.
      className={cn(
        "rounded-xl border border-border/60 bg-card/70 text-card-foreground transition-colors duration-140 hover:border-primary/30",
        className,
      )}
      {...props}
    />
  )
)
Card.displayName = "Card"

/** @deprecated Usá el vocabulario de `@/components/console/panel`. */
const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} data-slot="card-header" className={cn("flex flex-col space-y-1 px-4 pb-2.5 pt-3.5", className)} {...props} />
  )
)
CardHeader.displayName = "CardHeader"

/** @deprecated Usá el vocabulario de `@/components/console/panel`. */
const CardTitle = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("text-[12.5px] font-semibold leading-tight tracking-normal", className)} {...props} />
  )
)
CardTitle.displayName = "CardTitle"

/** @deprecated Usá el vocabulario de `@/components/console/panel`. */
const CardDescription = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("text-[10.5px] leading-[1.45] text-muted-foreground", className)} {...props} />
  )
)
CardDescription.displayName = "CardDescription"

/** @deprecated Usá el vocabulario de `@/components/console/panel`. */
const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} data-slot="card-content" className={cn("px-4 pb-3.5 pt-0", className)} {...props} />
  )
)
CardContent.displayName = "CardContent"

/** @deprecated Usá el vocabulario de `@/components/console/panel`. */
const CardFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("flex items-center px-4 pb-3.5 pt-0", className)} {...props} />
  )
)
CardFooter.displayName = "CardFooter"

export { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter }
