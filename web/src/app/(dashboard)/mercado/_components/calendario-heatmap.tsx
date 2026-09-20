"use client";

/**
 * El heatmap anual del Calendario: una columna por semana, siete filas
 * Lun→Dom. Pinta cierres de plazo (vista principal) o publicaciones.
 *
 * La escala de color es por tramos y la leyenda los enumera con su rango
 * («1-2», «3-5»…): sin ella el verde de una celda no significaría nada. Cada
 * celda lleva además su fecha y su conteo exacto —en la `Pista` al pasar el
 * puntero y como nombre accesible—, así que la cifra nunca aparece sin decir
 * de qué día es (ADR-014).
 *
 * En la vista de vencimientos, un día con cierres es un enlace al listado de
 * esas licitaciones (con el ámbito activo). Esos enlaces NO son paradas de
 * tabulación —365 harían la tarjeta intransitable—: el camino de teclado es la
 * lista «Próximos 7 días» y el día pico, que enlazan a lo mismo. Hoy lleva un
 * anillo y los seis días siguientes, uno más tenue.
 */

import Link from "next/link";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Pista } from "@/components/ui/pista";
import { Skeleton } from "@/components/ui/skeleton";
import { useScopedHref } from "@/lib/filters";
import { cn } from "@/lib/utils";
import { CalendarDays } from "lucide-react";

import {
  DAY_LABELS,
  diaHref,
  type CalendarioModo,
  type CalendarWeek,
  type DayCell,
  type MonthLabel,
} from "../_hooks/use-calendario-view";

const COLOR_SCALE = [
  { bg: "bg-gray-100 dark:bg-gray-800", label: "0" },
  { bg: "bg-green-100 dark:bg-green-900", label: "1-2" },
  { bg: "bg-green-200 dark:bg-green-800", label: "3-5" },
  { bg: "bg-green-300 dark:bg-green-700", label: "6-10" },
  { bg: "bg-green-400 dark:bg-green-600", label: "11-20" },
  { bg: "bg-green-500 dark:bg-green-500", label: "21-50" },
  { bg: "bg-green-600 dark:bg-green-400", label: "51+" },
];

function getColorClass(count: number): string {
  if (count === 0) return COLOR_SCALE[0].bg;
  if (count <= 2) return COLOR_SCALE[1].bg;
  if (count <= 5) return COLOR_SCALE[2].bg;
  if (count <= 10) return COLOR_SCALE[3].bg;
  if (count <= 20) return COLOR_SCALE[4].bg;
  if (count <= 50) return COLOR_SCALE[5].bg;
  return COLOR_SCALE[6].bg;
}

const TEXTOS: Record<CalendarioModo, { titulo: string; unidad: string; descripcion: string }> = {
  vencimientos: {
    titulo: "Cierres de plazo",
    unidad: "cierres",
    descripcion:
      "Licitaciones cuyo plazo de presentación termina cada día. Pulsa un día para ver cuáles; hoy y los próximos 7 días van resaltados.",
  },
  publicaciones: {
    titulo: "Densidad de Publicaciones",
    unidad: "publicaciones",
    descripcion: "Licitaciones publicadas cada día.",
  },
};

function Celda({
  cell,
  modo,
  scopedHref,
}: {
  cell: DayCell;
  modo: CalendarioModo;
  /** Resuelto una vez en la tarjeta: 365 celdas no abren 365 suscripciones a la URL. */
  scopedHref: (path: string) => string;
}) {
  const etiqueta = `${cell.dateStr}: ${cell.count} ${TEXTOS[modo].unidad}${cell.esHoy ? " (hoy)" : ""}`;
  const clase = cn(
    "block w-5 h-5 m-[1px] rounded-sm transition-colors",
    getColorClass(cell.count),
    cell.esHoy && "ring-2 ring-primary ring-offset-1 ring-offset-background",
    !cell.esHoy && cell.proximos7 && modo === "vencimientos" && "ring-1 ring-primary/60",
  );
  if (modo === "vencimientos" && cell.count > 0) {
    return (
      <Pista contenido={etiqueta}>
        <Link
          href={scopedHref(diaHref(cell.dateStr))}
          tabIndex={-1}
          aria-label={`${etiqueta}. Ver licitaciones`}
          className={cn(clase, "cursor-pointer hover:opacity-80")}
        />
      </Pista>
    );
  }
  return (
    <Pista contenido={etiqueta}>
      <div role="img" aria-label={etiqueta} className={cn(clase, "cursor-default")} />
    </Pista>
  );
}

export function CalendarioHeatmap({
  weeks,
  months,
  selectedYear,
  modo = "publicaciones",
  isLoading,
}: {
  weeks: CalendarWeek[];
  months: MonthLabel[];
  selectedYear: number;
  modo?: CalendarioModo;
  isLoading: boolean;
}) {
  const textos = TEXTOS[modo];
  const scopedHref = useScopedHref();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <CalendarDays className="h-5 w-5" aria-hidden="true" />
          {textos.titulo} — {selectedYear}
        </CardTitle>
        <CardDescription>{textos.descripcion}</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-[300px] w-full" />
        ) : weeks.length > 0 ? (
          <div className="overflow-x-auto">
            <div className="inline-block min-w-max">
              {/* Month labels */}
              <div className="flex ml-10">
                {months.map((m, idx) => {
                  const nextIdx = idx + 1 < months.length ? months[idx + 1].weekIdx : weeks.length;
                  const span = nextIdx - m.weekIdx;
                  return (
                    <div
                      key={`${m.label}-${idx}`}
                      className="text-xs text-muted-foreground"
                      style={{ width: `${span * 16}px` }}
                    >
                      {span >= 2 ? m.label : ""}
                    </div>
                  );
                })}
              </div>

              {/* Grid */}
              {DAY_LABELS.map((dayLabel, dayIdx) => (
                <div key={dayLabel} className="flex items-center">
                  <div className="w-10 shrink-0 text-xs text-muted-foreground text-right pr-2">
                    {dayIdx % 2 === 0 ? dayLabel : ""}
                  </div>
                  {weeks.map((week, weekIdx) => {
                    const cell = week.days[dayIdx];
                    if (!cell) {
                      return <div key={weekIdx} className="w-5 h-5 m-[1px] rounded-sm" />;
                    }
                    return (
                      <Celda key={weekIdx} cell={cell} modo={modo} scopedHref={scopedHref} />
                    );
                  })}
                </div>
              ))}

              {/* Legend */}
              <div className="flex items-center gap-2 mt-4 ml-10">
                <span className="text-xs text-muted-foreground">Menos</span>
                {COLOR_SCALE.map((c, i) => (
                  <Pista key={i} contenido={c.label}>
                    <div role="img" aria-label={c.label} className={cn("w-5 h-5 rounded-sm", c.bg)} />
                  </Pista>
                ))}
                <span className="text-xs text-muted-foreground">Mas</span>
              </div>
            </div>
          </div>
        ) : (
          <EmptyState />
        )}
      </CardContent>
    </Card>
  );
}
