import { cn } from "@/lib/utils";

/**
 * Marco de ventana para las capturas del producto.
 *
 * Existía dos veces —en el mock CSS del hero y otra vez, copiado a mano, en la
 * sección de captura—, con la misma etiqueta literal y los mismos tres puntos.
 * Al desaparecer el mock queda una sola pieza, que es lo que debió ser desde el
 * principio: la captura no es un adorno suelto, es «esto es una pantalla del
 * producto» y el cromo es lo que lo dice.
 *
 * `min-w-0` + `truncate` en la etiqueta no son decorativos: la versión anterior
 * era un `flex` de tres hijos sin contención, y por debajo de 360 px el texto
 * se recortaba en seco justo encima del fold.
 */
export function MarcoCaptura({
  etiqueta,
  children,
  className,
}: {
  etiqueta: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("border-border/70 bg-card tf-card-shadow overflow-hidden rounded-xl border", className)}>
      <div className="border-border/60 flex items-center gap-1.5 border-b px-4 py-2.5">
        <span className="bg-muted-foreground/25 h-2.5 w-2.5 shrink-0 rounded-full" />
        <span className="bg-muted-foreground/25 h-2.5 w-2.5 shrink-0 rounded-full" />
        <span className="bg-muted-foreground/25 h-2.5 w-2.5 shrink-0 rounded-full" />
        <span className="text-muted-foreground ml-3 min-w-0 truncate font-mono text-[10px] tracking-wide">
          {etiqueta}
        </span>
      </div>
      {children}
    </div>
  );
}
