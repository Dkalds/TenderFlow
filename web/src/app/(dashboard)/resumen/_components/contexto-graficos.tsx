/**
 * La barra apilada de la composición por estado y de los movimientos del
 * mercado. Dibuja el `por_estado` de `/analytics/overview` (o el `por_tipo` de
 * `/eventos`) tal como llega: no calcula nada que el backend no haya dado.
 * Es SVG con atributos y no anchos en `style` (scripts/check_inline_styles.py),
 * y es decorativa para el lector: la leyenda dice lo mismo en texto.
 *
 * Aquí vivía también `Sparkline`, el área del ritmo bajo «Publicadas 30 d» e
 * «Importe 30 d»; salió con ellas, porque repetía el gráfico de ritmo que va
 * debajo de la tira.
 */

import { cn } from "@/lib/utils";

export interface TramoEstado {
  estado: string;
  n: number;
  color: string;
  /** Expedientes de los tramos anteriores: dónde empieza este en la barra. */
  inicio: number;
}

/** Los tramos de la barra en el orden en que llegan, cada uno tras el anterior. */
export function tramosApilados(estados: readonly { estado: string; n: number; color: string }[]): TramoEstado[] {
  return estados.reduce<TramoEstado[]>((tramos, estado) => {
    const previo = tramos.at(-1);
    return [...tramos, { ...estado, inicio: previo ? previo.inicio + previo.n : 0 }];
  }, []);
}

export function BarraApilada({
  tramos,
  total,
  activos,
}: {
  tramos: readonly TramoEstado[];
  total: number;
  /** Estados filtrados: el resto se atenúa para que se vea qué queda. */
  activos: readonly string[];
}) {
  if (total <= 0) return null;
  return (
    <svg
      aria-hidden="true"
      viewBox={`0 0 ${total} 1`}
      preserveAspectRatio="none"
      className="h-3 w-full overflow-hidden rounded-md"
    >
      {tramos.map((tramo) => (
        <rect
          key={tramo.estado}
          x={tramo.inicio}
          width={tramo.n}
          height="1"
          fill={tramo.color}
          className={cn("stroke-card", activos.length > 0 && !activos.includes(tramo.estado) && "opacity-30")}
          strokeWidth="2"
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </svg>
  );
}
