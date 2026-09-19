"use client";

/**
 * Datos y rejilla de la vista Calendario.
 *
 * Dos métricas, las dos diarias y REALES del backend:
 *
 * - **Vencimientos** (vista principal, RFC ux-calendario #2-#4): cierres de
 *   plazo de presentación (`fecha_limite`) por día, desde
 *   `/analytics/calendario/vencimientos`. Cada día cuenta exactamente lo que
 *   abre `/detalle?cierre_desde=D&cierre_hasta=D` con el mismo ámbito, así que
 *   la celda es un enlace honesto (ADR-014, patrón 5).
 * - **Publicaciones** (vista secundaria): la serie `group_by=day` de
 *   `/analytics/trends`. Antes se repartía la serie SEMANAL ÷7 con un fudge de
 *   día laborable —el patrón 1 que prohíbe ADR-014—.
 *
 * Lo que se calcula aquí es geometría, no analítica: en qué semana y fila cae
 * cada día del año elegido, y las sumas por mes y día de la semana de esos
 * mismos conteos diarios.
 */

import { useMemo, useState } from "react";

import { useFilteredQuery } from "@/hooks/use-filtered-query";
import type { Schemas, TrendPoint } from "@/lib/api-types";

interface TrendsResponse {
  series: TrendPoint[];
}

export type VencimientosResponse = Schemas["VencimientosResult"];

export type CalendarioModo = "vencimientos" | "publicaciones";

export const DAY_LABELS = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"];
const MONTH_NAMES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];

/**
 * Años navegables en la vista de vencimientos: no hay una serie de la que
 * deducirlos sin pedirla entera, y un plazo de presentación rara vez cae a más
 * de un año vista. Un año sin cierres se pinta vacío, no se inventa.
 */
const VENCIMIENTOS_ANIOS_ATRAS = 5;
const VENCIMIENTOS_ANIOS_ADELANTE = 1;

export interface DayValue {
  count: number;
  importe: number;
}

export interface DayCell {
  date: Date;
  count: number;
  dateStr: string;
  esHoy: boolean;
  /** Hoy o uno de los seis días siguientes. */
  proximos7: boolean;
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
  count: number;
  importe: number;
}

export interface DowPoint {
  dia: string;
  promedio: number;
}

/** `YYYY-MM-DD` en hora LOCAL (la rejilla se construye con fechas locales). */
export function isoLocal(d: Date): string {
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

/** Enlace al listado de las licitaciones que cierran ese día. */
export function diaHref(fecha: string): string {
  return `/detalle?cierre_desde=${fecha}&cierre_hasta=${fecha}`;
}

/** Conteo e importe por día desde la serie diaria de publicaciones. */
export function dayMapFromTrends(series: TrendPoint[] | undefined): Map<string, DayValue> {
  const map = new Map<string, DayValue>();
  for (const p of series ?? []) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(p.period)) continue;
    const prev = map.get(p.period) ?? { count: 0, importe: 0 };
    map.set(p.period, { count: prev.count + p.count, importe: prev.importe + (p.importe ?? 0) });
  }
  return map;
}

/** Conteo e importe por día desde la serie de vencimientos. */
export function dayMapFromVencimientos(data: VencimientosResponse | undefined): Map<string, DayValue> {
  const map = new Map<string, DayValue>();
  for (const d of data?.dias ?? []) {
    map.set(d.fecha, { count: d.count, importe: d.importe });
  }
  return map;
}

/** Rejilla semanal Lun→Dom del año, con hoy y los próximos 7 días marcados. */
export function buildCalendarGrid(
  days: Map<string, DayValue>,
  year: number,
  today: Date,
): { weeks: CalendarWeek[]; months: MonthLabel[] } {
  const hoy = isoLocal(today);
  const limite7 = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 7);
  const limite7Str = isoLocal(limite7);

  const startDate = new Date(year, 0, 1);
  const endDate = new Date(year, 11, 31);
  const dow = startDate.getDay() || 7;
  startDate.setDate(startDate.getDate() - (dow - 1));

  const weeks: CalendarWeek[] = [];
  const months: MonthLabel[] = [];
  let lastMonth = -1;
  const current = new Date(startDate);

  while (current <= endDate) {
    const week: (DayCell | null)[] = [];
    const weekStart = new Date(current);
    for (let d = 0; d < 7; d++) {
      const dayDate = new Date(current.getFullYear(), current.getMonth(), current.getDate() + d);
      if (dayDate.getFullYear() !== year) {
        week.push(null);
        continue;
      }
      const key = isoLocal(dayDate);
      week.push({
        date: dayDate,
        count: days.get(key)?.count ?? 0,
        dateStr: key,
        esHoy: key === hoy,
        proximos7: key >= hoy && key < limite7Str,
      });
      if (dayDate.getMonth() !== lastMonth && d === 0) {
        lastMonth = dayDate.getMonth();
        months.push({ label: MONTH_NAMES[dayDate.getMonth()], weekIdx: weeks.length });
      }
    }
    weeks.push({ weekStart, days: week });
    current.setDate(current.getDate() + 7);
  }
  return { weeks, months };
}

/** Suma por mes (sólo el año elegido). */
export function monthlyFromDays(days: Map<string, DayValue>, year: number): MonthlyPoint[] {
  const agg = new Map<string, DayValue>();
  for (const [key, v] of days) {
    if (!key.startsWith(`${year}-`)) continue;
    const mes = key.slice(0, 7);
    const prev = agg.get(mes) ?? { count: 0, importe: 0 };
    agg.set(mes, { count: prev.count + v.count, importe: prev.importe + v.importe });
  }
  return Array.from(agg.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([mes, v]) => ({
      mes: MONTH_NAMES[parseInt(mes.slice(5, 7), 10) - 1],
      count: v.count,
      importe: v.importe,
    }));
}

/** Media por día de la semana sobre los días CON dato del año elegido. */
export function dowFromDays(days: Map<string, DayValue>, year: number): DowPoint[] {
  const totals = [0, 0, 0, 0, 0, 0, 0];
  const counts = [0, 0, 0, 0, 0, 0, 0];
  for (const [key, v] of days) {
    if (!key.startsWith(`${year}-`)) continue;
    const [y, m, d] = key.split("-").map(Number);
    const dow = (new Date(y, m - 1, d).getDay() + 6) % 7;
    totals[dow] += v.count;
    counts[dow] += 1;
  }
  return DAY_LABELS.map((label, i) => ({
    dia: label,
    promedio: counts[i] > 0 ? Math.round(totals[i] / counts[i]) : 0,
  }));
}

export function useCalendarioView() {
  const currentYear = new Date().getFullYear();
  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [modo, setModo] = useState<CalendarioModo>("vencimientos");

  const vencimientos = useFilteredQuery<VencimientosResponse>(
    ["analytics", "calendario-vencimientos", String(selectedYear)],
    "/api/v1/analytics/calendario/vencimientos",
    { staleTime: 5 * 60 * 1000, enabled: modo === "vencimientos" },
    { desde: `${selectedYear}-01-01`, hasta: `${selectedYear}-12-31` },
  );

  const publicaciones = useFilteredQuery<TrendsResponse>(
    ["analytics", "trends", "day"],
    "/api/v1/analytics/trends?group_by=day",
    { staleTime: 5 * 60 * 1000, enabled: modo === "publicaciones" },
  );

  const activa = modo === "vencimientos" ? vencimientos : publicaciones;

  const dayMap = useMemo(
    () =>
      modo === "vencimientos"
        ? dayMapFromVencimientos(vencimientos.data)
        : dayMapFromTrends(publicaciones.data?.series),
    [modo, vencimientos.data, publicaciones.data],
  );

  const availableYears = useMemo(() => {
    if (modo === "vencimientos") {
      const years: number[] = [];
      for (let y = currentYear - VENCIMIENTOS_ANIOS_ATRAS; y <= currentYear + VENCIMIENTOS_ANIOS_ADELANTE; y++) {
        years.push(y);
      }
      return years;
    }
    const years = new Set<number>();
    for (const key of dayMap.keys()) years.add(parseInt(key.slice(0, 4), 10));
    const sorted = Array.from(years).sort((a, b) => a - b);
    return sorted.length > 0 ? sorted : [currentYear];
  }, [modo, dayMap, currentYear]);

  // Sin ningún día con dato no se pinta una rejilla de ceros: la tarjeta cae
  // en su estado vacío, que dice lo mismo sin parecer una medición.
  const { weeks, months } = useMemo(
    () =>
      dayMap.size === 0
        ? { weeks: [], months: [] }
        : buildCalendarGrid(dayMap, selectedYear, new Date()),
    [dayMap, selectedYear],
  );
  const monthlyData = useMemo(() => monthlyFromDays(dayMap, selectedYear), [dayMap, selectedYear]);
  const dowData = useMemo(() => dowFromDays(dayMap, selectedYear), [dayMap, selectedYear]);

  return {
    modo,
    setModo,
    weeks,
    months,
    monthlyData,
    dowData,
    availableYears,
    selectedYear,
    setSelectedYear,
    vencimientos: vencimientos.data,
    isLoading: activa.isLoading,
    error: activa.error,
  };
}
