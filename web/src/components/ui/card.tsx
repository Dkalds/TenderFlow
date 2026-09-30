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
 * La migración terminó el 2026-09-27: los 106 ficheros que lo importaban
 * pasaron a `@/components/console/panel`, área por área y con revisión, no de
 * golpe. Desde entonces `no-restricted-imports` (`importacionesRetiradas` en
 * `eslint.config.mjs`) impide importarlo fuera de los tests, con `deudaCard`
 * —la lista de importadores que solo puede encoger— vacía desde el día que se
 * escribió. El módulo se conserva, deprecado, porque su test fija cómo pinta;
 * borrarlo es el paso siguiente.
 *
 * Dibuja igual que `Panel` en lo que comparten: superficie
 * opaca, sin hover (un bloque que no se pulsa no reacciona al ratón), título a
 * 13 px y descripción a 12, por encima de la etiqueta de un campo y no por
 * debajo.
 *
 * @deprecated Usa `Panel` / `PanelTitle` de `@/components/console/panel`.
 */

/** @deprecated Usa `Panel` de `@/components/console/panel`. */
function Card({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card"
      // Panel de consola, no tarjeta elevada: borde tenue, superficie opaca y
      // sin sombra. Translúcida sobre un fondo plano solo daba un segundo
      // blanco; y el borde que se encendía al pasar el ratón prometía un clic
      // que no existía.
      className={cn("rounded-xl border border-border/60 bg-card text-card-foreground", className)}
      {...props}
    />
  )
}

/** @deprecated Usa el vocabulario de `@/components/console/panel`. */
function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-header" className={cn("flex flex-col space-y-1 px-4 pb-2.5 pt-3.5", className)} {...props} />
}

/** @deprecated Usa `PanelTitle` de `@/components/console/panel`. */
function CardTitle({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("text-tf-body font-semibold leading-tight", className)} {...props} />
}

/** @deprecated Usa el `hint` de `PanelTitle` de `@/components/console/panel`. */
function CardDescription({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("text-tf-meta text-muted-foreground", className)} {...props} />
}

/** @deprecated Usa el vocabulario de `@/components/console/panel`. */
function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-content" className={cn("px-4 pb-3.5 pt-0", className)} {...props} />
}

/** @deprecated Usa el vocabulario de `@/components/console/panel`. */
function CardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("flex items-center px-4 pb-3.5 pt-0", className)} {...props} />
}

export { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter }
