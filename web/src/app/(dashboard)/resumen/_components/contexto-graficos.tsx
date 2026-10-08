/**
 * Las dos piezas visuales de «Contexto de mercado»: la línea del ritmo bajo
 * «Publicadas 30 d» y la barra apilada de la composición por estado.
 *
 * Ninguna calcula nada que el backend no haya dado: la línea dibuja la serie
 * diaria de `/analytics/trends` y la barra, el `por_estado` de
 * `/analytics/overview`. Las dos son SVG con atributos y no anchos en `style`
 * (scripts/check_inline_styles.py), y las dos son decorativas para el lector:
 * la cifra y la leyenda dicen lo mismo en texto.
 */

import { CHART_SERIES } from "@/lib/chart-colors";
import { cn } from "@/lib/utils";

/**
 * `points` de una polilínea que ocupa `ancho`×`alto`, con el cero abajo y el
 * máximo de la serie arriba (con un píxel de aire para el trazo).
 */
export function puntosSparkline(valores: readonly number[], ancho: number, alto: number): string {
  if (valores.length < 2) return "";
  const maximo = Math.max(...valores);
  const paso = ancho / (valores.length - 1);
  return valores
    .map((valor, indice) => {
      const y = maximo > 0 ? alto - 1 - (valor / maximo) * (alto - 2) : alto - 1;
      return `${(indice * paso).toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

export function Sparkline({ valores, className }: { valores: readonly number[]; className?: string }) {
  const puntos = puntosSparkline(valores, 100, 24);
  if (!puntos) return null;
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 100 24"
      preserveAspectRatio="none"
      className={cn("h-6 w-full overflow-visible", className)}
    >
      <polyline
        points={puntos}
        fill="none"
        stroke={CHART_SERIES[0]}
        strokeWidth="1.5"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

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
