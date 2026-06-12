"use client";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import type { TrendPoint } from "@/generated/api";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
const CalendarioMonthlyChart = dynamic(() => import("@/components/charts/calendario-charts").then(m => ({ default: m.CalendarioMonthlyChart })), { ssr: false, loading: () => <Skeleton className="h-[300px] w-full rounded-md" /> });
const CalendarioDowChart = dynamic(() => import("@/components/charts/calendario-charts").then(m => ({ default: m.CalendarioDowChart })), { ssr: false, loading: () => <Skeleton className="h-[200px] w-full rounded-md" /> });

interface TrendsResponse {
  series: TrendPoint[];
}

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

const DAY_LABELS = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"];
const MONTH_NAMES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];

interface DayCell {
  date: Date;
  count: number;
  dateStr: string;
}

interface CalendarWeek {
  weekStart: Date;
  days: (DayCell | null)[];
}

export default function CalendarioPage() {
  const currentYear = new Date().getFullYear();
  const [selectedYear, setSelectedYear] = useState(currentYear);

  const { data, isLoading, error } = useFilteredQuery<TrendsResponse>(
    ["analytics", "trends", "week"],
    "/api/v1/analytics/trends?group_by=week",
    { staleTime: 5 * 60 * 1000 },
  );

  // Build daily counts from weekly series
  const dailyCounts = useMemo(() => {
    const counts = new Map<string, number>();
    if (!data?.series) return counts;

    for (const point of data.series) {
      const date = new Date(point.period);
      if (!isNaN(date.getTime())) {
        for (let d = 0; d < 7; d++) {
          const day = new Date(date);
          day.setDate(day.getDate() + d);
          const key = day.toISOString().slice(0, 10);
          const dailyShare = Math.round(point.count / 7);
          counts.set(key, (counts.get(key) ?? 0) + (d < 5 ? dailyShare + 1 : dailyShare));
        }
      } else {
        const weekMatch = point.period.match(/^(\d{4})-W(\d{2})$/);
        if (weekMatch) {
          const year = parseInt(weekMatch[1]);
          const week = parseInt(weekMatch[2]);
          const jan4 = new Date(year, 0, 4);
          const dayOfWeek = jan4.getDay() || 7;
          const monday = new Date(jan4);
          monday.setDate(jan4.getDate() - dayOfWeek + 1 + (week - 1) * 7);
          for (let d = 0; d < 7; d++) {
            const day = new Date(monday);
            day.setDate(monday.getDate() + d);
            const key = day.toISOString().slice(0, 10);
            const dailyShare = Math.round(point.count / 7);
            counts.set(key, (counts.get(key) ?? 0) + dailyShare);
          }
        } else {
          const monthDate = new Date(point.period + "-01");
          if (!isNaN(monthDate.getTime())) {
            const daysInMonth = new Date(monthDate.getFullYear(), monthDate.getMonth() + 1, 0).getDate();
            const dailyShare = Math.round(point.count / daysInMonth);
            for (let d = 0; d < daysInMonth; d++) {
              const day = new Date(monthDate);
              day.setDate(day.getDate() + d);
              const key = day.toISOString().slice(0, 10);
              counts.set(key, dailyShare);
            }
          }
        }
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
  const { weeks, months } = useMemo(() => {
    if (dailyCounts.size === 0) return { weeks: [], months: [] };

    const startDate = new Date(selectedYear, 0, 1);
    const endDate = new Date(selectedYear, 11, 31);

    // Align to Monday
    const dow = startDate.getDay() || 7;
    startDate.setDate(startDate.getDate() - (dow - 1));

    const calWeeks: CalendarWeek[] = [];
    const monthLabels: { label: string; weekIdx: number }[] = [];
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
  const monthlyData = useMemo(() => {
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
  const dowData = useMemo(() => {
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

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center" role="alert">
        <p className="text-destructive">
          {t("common.error")}: {(error as Error).message}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Calendario</h1>
          <p className="text-muted-foreground">
            Heatmap de publicaciones por fecha.
          </p>
        </div>

        {/* Year selector */}
        <div className="flex items-center gap-1">
          <Button
            variant="outline"
            size="icon"
            className="h-8 w-8"
            onClick={() => setSelectedYear((y) => Math.max(availableYears[0], y - 1))}
            disabled={selectedYear <= availableYears[0]}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="px-3 text-sm font-medium tabular-nums">{selectedYear}</span>
          <Button
            variant="outline"
            size="icon"
            className="h-8 w-8"
            onClick={() => setSelectedYear((y) => Math.min(availableYears[availableYears.length - 1], y + 1))}
            disabled={selectedYear >= availableYears[availableYears.length - 1]}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Heatmap */}
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

      {/* Monthly bars */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Publicaciones por Mes — {selectedYear}</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[300px] w-full" />
          ) : monthlyData.length > 0 ? (
            <CalendarioMonthlyChart data={monthlyData} />
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>

      {/* Day-of-week distribution */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Distribucion por Dia de la Semana — {selectedYear}</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[200px] w-full" />
          ) : dowData.some((d) => d.promedio > 0) ? (
            <CalendarioDowChart data={dowData} />
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
