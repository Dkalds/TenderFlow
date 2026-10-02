import { cn } from "@/lib/utils"

/**
 * Esqueleto de carga: el único lenguaje de carga de la app (el barrido
 * `tf-shimmer` de `globals.css`, que se queda quieto con reduced-motion). Nada
 * de `animate-pulse` de shadcn al lado: dos lenguajes de carga en la misma
 * pantalla se leen como dos cosas cargando.
 *
 * `data-slot="skeleton"` es la manija estable para los tests: la clase del
 * barrido puede cambiar, el papel no.
 */
function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div data-slot="skeleton" className={cn("tf-shimmer rounded-md", className)} {...props} />
}

function SkeletonTable({ rows = 6, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)}>
      <Skeleton className="h-9 w-full" />
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  )
}

export { Skeleton, SkeletonTable }
