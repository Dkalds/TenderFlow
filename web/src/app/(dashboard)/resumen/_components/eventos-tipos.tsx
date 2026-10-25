"use client";

/**
 * El vocabulario de los tipos de movimiento del feed: icono, nombre, color de
 * serie, la variación de importe y la leyenda que filtra por tipo. Vive aparte
 * de `eventos-feed.tsx` para que el panel quepa en el tope de líneas de
 * `src/app`.
 */

import {
  ArrowRightLeft,
  CalendarClock,
  FileCheck,
  type LucideIcon,
  CircleX,
  RefreshCw,
  Scale,
  Trophy,
} from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { getSeriesColor } from "@/lib/chart-colors";
import { cn, formatCurrency, formatNumber } from "@/lib/utils";
import type { TramoEstado } from "./contexto-graficos";

export const TIPO_ICON: Record<string, LucideIcon> = {
  adjudicacion: Trophy,
  formalizacion: FileCheck,
  modificacion: RefreshCw,
  prorroga: CalendarClock,
  anulacion: CircleX,
  cambio_estado: ArrowRightLeft,
  recurso: Scale,
};

export const TIPO_LABEL: Record<string, string> = {
  adjudicacion: "Adjudicación",
  formalizacion: "Formalización",
  modificacion: "Modificación",
  prorroga: "Prórroga",
  anulacion: "Anulación",
  cambio_estado: "Cambio de estado",
  recurso: "Recurso",
};

/**
 * Color de cada clase de movimiento en la línea de tiempo: por posición en la
 * serie de la consola, fijo de un día a otro. El cambio de estado —y lo que no
 * se sabe nombrar— va en el gris de «Otros» (`chart-8`).
 */
const TIPO_SERIE: Record<string, number> = {
  adjudicacion: 1,
  formalizacion: 5,
  modificacion: 2,
  prorroga: 9,
  anulacion: 8,
  recurso: 4,
  cambio_estado: 7,
};

export function colorDeTipo(tipo: string): string {
  return getSeriesColor(TIPO_SERIE[tipo] ?? 7);
}

/**
 * Variación del importe del contrato.
 *
 * Iba en rojo cuando subía y en verde cuando bajaba, con `text-red-600` /
 * `text-green-400` a pelo — fuera del sistema de tokens y, peor, emitiendo un
 * juicio que el dato no contiene: que un contrato del mercado crezca no es malo
 * para quien mira el mercado. Queda el signo, que es lo que sí dice el dato.
 */
export function ImporteDelta({ value }: { value: number | null | undefined }) {
  if (value == null || value === 0) return null;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        {/* Sin `tabIndex` ni `<button>`: esto vive dentro de un `<Link>`, y un
            control focusable aquí sería `nested-interactive` — la primera regla
            que C7.1 quiere reactivar. */}
        <span className="tf-tnum flex-none text-tf-micro font-semibold">
          {value > 0 ? "+" : ""}
          {formatCurrency(value)}
        </span>
      </TooltipTrigger>
      <TooltipContent>Variación del importe del contrato</TooltipContent>
    </Tooltip>
  );
}

/**
 * Leyenda del reparto por tipo: el nombre de cada clase, su color en la barra
 * y su recuento. Es la que dice el reparto al lector de pantalla; la barra es
 * decorativa. Cada tipo es un botón que deja la lista en los movimientos de esa
 * clase (uno a la vez, que es lo que filtra `GET /eventos?tipo=`); pulsarlo
 * otra vez vuelve a todos.
 */
export function LeyendaTipos({
  tramos,
  activo,
  onTipo,
}: {
  tramos: readonly TramoEstado[];
  activo: string | null;
  onTipo: (tipo: string | null) => void;
}) {
  return (
    <ul aria-label="Movimientos por tipo" className="-mx-1.5 flex flex-wrap gap-x-1 gap-y-0.5">
      {tramos.map((tramo) => {
        const pulsado = activo === tramo.estado;
        return (
          <li key={tramo.estado}>
            <button
              type="button"
              aria-pressed={pulsado}
              onClick={() => onTipo(pulsado ? null : tramo.estado)}
              className={cn(
                "inline-flex h-6 items-center gap-1.5 rounded-md px-1.5 text-tf-micro text-muted-foreground transition-colors active:duration-0",
                pulsado ? "bg-primary-selected text-foreground" : "hover:bg-primary-hover active:bg-primary-selected",
              )}
            >
              {/* Con otro tipo pulsado se atenúa solo el punto: el texto atenuado
                  bajaba de 4,5:1 en el tema oscuro (WCAG 1.4.3). */}
              <svg
                aria-hidden="true"
                viewBox="0 0 8 8"
                className={cn("h-2 w-2 flex-none", activo !== null && !pulsado && "opacity-30")}
              >
                <circle cx="4" cy="4" r="4" fill={tramo.color} />
              </svg>
              {TIPO_LABEL[tramo.estado] ?? tramo.estado}
              <span className="tf-tnum font-semibold text-foreground">{formatNumber(tramo.n)}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
