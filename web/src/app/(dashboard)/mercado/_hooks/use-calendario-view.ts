"use client";

/**
 * Datos y rejilla de la vista Calendario.
 *
 * La única fuente es la serie DIARIA del backend (`group_by=day`): cada celda
 * del heatmap es el conteo real de publicaciones de ese día. Antes se repartía
 * la serie SEMANAL ÷7 con un fudge de día laborable, que es exactamente el
 * patrón 1 que prohíbe ADR-014 — una cifra inventada en el cliente.
 *
 * Lo que se calcula aquí es geometría, no analítica: en qué semana y en qué
 * fila cae cada día del año elegido, y las sumas por mes y por día de la semana
 * de esos mismos conteos.
 */

import { useMemo, useState } from "react";

import { useFilteredQuery } from "@/hooks/use-filtered-query";
import type { TrendPoint } from "@/lib/api-types";

interface TrendsResponse {
  series: TrendPoint[];
}

export const DAY_LABELS = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"];
const MONTH_NAMES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];

export interface DayCell {
  date: Date;
  count: number;
  dateStr: string;
}

export interface CalendarWeek {
  weekStart: Date;
  /** Siete posiciones Lun→Dom; `null` en los días que caen fuera del año. */
  days: (DayCell | null)[];
}

/** Etiqueta de mes anclada a la columna donde empieza. */
export interface MonthLabel {
  label: string;
  weekIdx: number;
}

export interface MonthlyPoint {
  mes: string;
  publicaciones: number;
  importe: number;
}

export interface DowPoint {
  dia: string;
  promedio: number;
}

export function useCalendarioView() {
  const currentYear = new Date().getFullYear();
  const [selectedYear, setSelectedYear] = useState(currentYear);

  const { data, isLoading, error } = useFilteredQuery<TrendsResponse>(
    ["analytics", "trends", "day"],
    "/api/v1/analytics/trends?group_by=day",
    { staleTime: 5 * 60 * 1000 },
  );

  // Conteos diarios REALES del backend (group_by=day): period = "YYYY-MM-DD".
  const dailyCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const point of data?.series ?? []) {
      if (/^\d{4}-\d{2}-\d{2}$/.test(point.period)) {
        counts.set(point.period, (counts.get(point.period) ?? 0) + point.count);
      }
    }
    return counts;
  }, [data]);

  // Available years
  const availableYears = useMemo(() => {
    const years = new Set<number>();
    for (const key of dailyCounts.keys()) {
      years.add(parseInt(key.slice(0, 4)));
    }
    const sorted = Array.from(years).sort();
    return sorted.length > 0 ? sorted : [currentYear];
  }, [dailyCounts, currentYear]);

  // Heatmap grid filtered by selected year
  const { weeks, months } = useMemo<{ weeks: CalendarWeek[]; months: MonthLabel[] }>(() => {
    if (dailyCounts.size === 0) return { weeks: [], months: [] };

    const startDate = new Date(selectedYear, 0, 1);
    const endDate = new Date(selectedYear, 11, 31);

    // Align to Monday
    const dow = startDate.getDay() || 7;
    startDate.setDate(startDate.getDate() - (dow - 1));

    const calWeeks: CalendarWeek[] = [];
    const monthLabels: MonthLabel[] = [];
    let lastMonth = -1;
    const current = new Date(startDate);

    while (current <= endDate) {
      const week: (DayCell | null)[] = [];
      const weekStart = new Date(current);

      for (let d = 0; d < 7; d++) {
        const dayDate = new Date(current);
        dayDate.setDate(current.getDate() + d);
        const key = dayDate.toISOString().slice(0, 10);

        if (dayDate.getFullYear() !== selectedYear) {
          week.push(null);
        } else {
          const count = dailyCounts.get(key) ?? 0;
          week.push({ date: dayDate, count, dateStr: key });

          if (dayDate.getMonth() !== lastMonth && d === 0) {
            lastMonth = dayDate.getMonth();
            monthLabels.push({
              label: MONTH_NAMES[dayDate.getMonth()],
              weekIdx: calWeeks.length,
            });
          }
        }
      }

      calWeeks.push({ weekStart, days: week });
      current.setDate(current.getDate() + 7);
    }

    return { weeks: calWeeks, months: monthLabels };
  }, [dailyCounts, selectedYear]);

  // Monthly aggregation for bar chart
  const monthlyData = useMemo<MonthlyPoint[]>(() => {
    const agg = new Map<string, { count: number; importe: number }>();
    for (const [key, count] of dailyCounts.entries()) {
      if (!key.startsWith(String(selectedYear))) continue;
      const month = key.slice(0, 7);
      const prev = agg.get(month) ?? { count: 0, importe: 0 };
      agg.set(month, { count: prev.count + count, importe: prev.importe });
    }
    // Also aggregate importe from series if available
    if (data?.series) {
      for (const point of data.series) {
        const d = new Date(point.period);
        if (!isNaN(d.getTime()) && d.getFullYear() === selectedYear) {
          const month = d.toISOString().slice(0, 7);
          const prev = agg.get(month) ?? { count: 0, importe: 0 };
          agg.set(month, { count: prev.count, importe: prev.importe + (point.importe ?? 0) });
        }
      }
    }
    return Array.from(agg.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([mes, v]) => ({
        mes: MONTH_NAMES[parseInt(mes.slice(5, 7)) - 1],
        publicaciones: v.count,
        importe: v.importe,
      }));
  }, [dailyCounts, data, selectedYear]);

  // Day-of-week distribution
  const dowData = useMemo<DowPoint[]>(() => {
    const totals = [0, 0, 0, 0, 0, 0, 0];
    const counts = [0, 0, 0, 0, 0, 0, 0];
    for (const [key, count] of dailyCounts.entries()) {
      if (!key.startsWith(String(selectedYear))) continue;
      const d = new Date(key);
      // JS: 0=Sun, convert to 0=Mon
      const dow = (d.getDay() + 6) % 7;
      totals[dow] += count;
      counts[dow] += 1;
    }
    return DAY_LABELS.map((label, i) => ({
      dia: label,
      promedio: counts[i] > 0 ? Math.round(totals[i] / counts[i]) : 0,
    }));
  }, [dailyCounts, selectedYear]);

  return {
    weeks,
    months,
    monthlyData,
    dowData,
    availableYears,
    selectedYear,
    setSelectedYear,
    isLoading,
    error,
  };
}
