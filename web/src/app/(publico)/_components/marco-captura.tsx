import { cn } from "@/lib/utils";

/**
 * Marco de las capturas del producto: un borde, una línea con la pantalla que
 * se ve y la imagen.
 *
 * Existía dos veces —en el mock CSS del hero y otra vez, copiado a mano, en la
 * sección de captura—, con la misma etiqueta literal. Al desaparecer el mock
 * queda una sola pieza: la captura no es un adorno suelto, es «esto es una
 * pantalla del producto», y la línea de arriba es lo que lo dice.
 *
 * Sin los tres puntos de semáforo ni sombra (2026-09-26): el cromo de ventana
 * de macOS dibujado a mano es uno de los gestos que la propia portada nombra
 * como esqueleto de plantilla, y la superficie pública no lleva sombra en lo
 * que no flota. La etiqueta, en sans: nombra una pantalla, no es un código.
 *
 * `min-w-0` + `truncate` en la etiqueta no son decorativos: sin contención,
 * por debajo de 360 px el texto se recortaba en seco justo encima del fold.
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
    <div className={cn("border-border/70 bg-card overflow-hidden rounded-xl border", className)}>
      <div className="border-border/60 flex items-center border-b px-4 py-2.5">
        <span className="text-muted-foreground text-tf-micro min-w-0 truncate font-medium">{etiqueta}</span>
      </div>
      {children}
    </div>
  );
}
