/**
 * Los dibujos que acompañan a las cifras del Resumen: cada número lleva debajo
 * la forma que lo sitúa, como las celdas de Competencia (`competidores-cifras`).
 *
 * Ninguno calcula nada: los puntos son el recuento que mandó el backend y el
 * reloj coloca cada expediente de la cola por su propio plazo. Son SVG o cajas
 * con clases, sin `style` en línea (scripts/check_inline_styles.py), sin
 * transición —son una medida, no algo que se mueva— y decorativos para el
 * lector de pantalla: la cifra va escrita al lado.
 */

import { cn, formatNumber } from "@/lib/utils";

/** Puntos que caben en una fila de celda; el resto se dice en texto. */
export const TOPE_PUNTOS = 20;

export type TonoPuntos = "destructive" | "warning" | "primary" | "muted";

const RELLENO_PUNTO: Record<TonoPuntos, string> = {
  destructive: "bg-destructive",
  warning: "bg-warning",
  primary: "bg-primary",
  muted: "bg-muted-foreground/40",
};

/**
 * Gráfico de unidades: un cuadrado por elemento contado, hasta `TOPE_PUNTOS`.
 * Para recuentos pequeños —los compromisos de una organización— dice «tres» o
 * «diecisiete» antes de leer la cifra, y con cero deja el carril vacío en vez
 * de desaparecer, para que las celdas vecinas no salten.
 */
export function PuntosUnidad({
  n,
  tono = "primary",
  className,
}: {
  n: number;
  tono?: TonoPuntos;
  className?: string;
}) {
  const visibles = Math.max(0, Math.min(n, TOPE_PUNTOS));
  const resto = n - visibles;
  return (
    <span aria-hidden="true" className={cn("flex h-2 items-center gap-0.5", className)}>
      {visibles === 0 ? (
        <span className="h-px w-full bg-border/60" />
      ) : (
        Array.from({ length: visibles }, (_, indice) => (
          <span key={indice} className={cn("h-2 w-2 flex-none rounded-sm", RELLENO_PUNTO[tono])} />
        ))
      )}
      {resto > 0 && (
        <span className="tf-tnum ml-1 text-tf-micro font-medium text-muted-foreground">+{formatNumber(resto)}</span>
      )}
    </span>
  );
}

/** La ventana del reloj, en horas: el ancho entero de la regla. */
export const VENTANA_RELOJ_HORAS = 48;

/** Posición en la regla, en porcentaje, de un plazo a `horas` de ahora. */
export function posicionEnReloj(horas: number): number {
  return Math.max(0, Math.min(100, (horas / VENTANA_RELOJ_HORAS) * 100));
}

/**
 * El reloj de cierre: la regla de las próximas 48 horas con un punto por
 * expediente en su plazo. La lista de debajo dice cuáles; esto dice cómo se
 * reparten —si la cola se amontona esta tarde o viene repartida—, que con
 * cuatro filas no se ve.
 *
 * SVG sin `viewBox` y con coordenadas en porcentaje: así los puntos siguen
 * siendo círculos a cualquier ancho. Cada punto lleva un anillo del color de
 * la tarjeta, para que dos plazos juntos se lean como dos.
 */
export function RelojCierre({ horas, className }: { horas: readonly number[]; className?: string }) {
  return (
    <div aria-hidden="true" className={cn("px-1", className)}>
      <svg className="h-4 w-full overflow-visible">
        <rect x="0" y="6" width="50%" height="4" rx="2" className="fill-destructive/15" />
        <rect x="50%" y="6" width="50%" height="4" rx="2" className="fill-warning/15" />
        {horas.map((valor, indice) => (
          <circle
            key={indice}
            cx={`${posicionEnReloj(valor)}%`}
            cy="8"
            r="4"
            className={cn("stroke-card", valor <= 24 ? "fill-destructive" : "fill-warning")}
            strokeWidth="2"
          />
        ))}
      </svg>
      <div className="mt-0.5 flex justify-between text-tf-micro text-muted-foreground">
        <span>Ahora</span>
        <span>24 h</span>
        <span>48 h</span>
      </div>
    </div>
  );
}
