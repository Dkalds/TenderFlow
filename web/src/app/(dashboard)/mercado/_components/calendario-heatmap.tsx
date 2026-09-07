"use client";

/**
 * El heatmap anual de publicaciones: una columna por semana, siete filas
 * Lun→Dom.
 *
 * La escala de color es por tramos y la leyenda los enumera con su rango
 * («1-2», «3-5»…): sin ella el verde de una celda no significaría nada. Cada
 * celda lleva además su fecha y su conteo exacto en el `title`, así que la
 * cifra nunca aparece sin decir de qué día es (ADR-014).
 */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { CalendarDays } from "lucide-react";

import {
  DAY_LABELS,
  type CalendarWeek,
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

export function CalendarioHeatmap({
  weeks,
  months,
  selectedYear,
  isLoading,
}: {
  weeks: CalendarWeek[];
  months: MonthLabel[];
  selectedYear: number;
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <CalendarDays className="h-5 w-5" />
          Densidad de Publicaciones — {selectedYear}
        </CardTitle>
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
                      return (
                        <div key={weekIdx} className="w-5 h-5 m-[1px] rounded-sm" />
                      );
                    }
                    return (
                      <div
                        key={weekIdx}
                        className={cn(
                          "w-5 h-5 m-[1px] rounded-sm transition-colors cursor-default",
                          getColorClass(cell.count),
                        )}
                        title={`${cell.dateStr}: ${cell.count} publicaciones`}
                      />
                    );
                  })}
                </div>
              ))}

              {/* Legend */}
              <div className="flex items-center gap-2 mt-4 ml-10">
                <span className="text-xs text-muted-foreground">Menos</span>
                {COLOR_SCALE.map((c, i) => (
                  <div key={i} className={cn("w-5 h-5 rounded-sm", c.bg)} title={c.label} />
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
