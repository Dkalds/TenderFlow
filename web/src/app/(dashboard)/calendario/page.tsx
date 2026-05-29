"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type { TrendPoint } from "@/generated/api";
import { CalendarDays } from "lucide-react";

interface TrendsResponse {
  series: TrendPoint[];
}

async function fetchTrends(): Promise<TrendsResponse> {
  const res = await fetch("/api/v1/analytics/trends?group_by=week", {
    credentials: "include",
  });
  if (!res.ok) throw new Error("Failed to fetch trends");
  return res.json();
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
  const { data, isLoading, error } = useQuery({
    queryKey: ["analytics", "trends", "week"],
    queryFn: fetchTrends,
    staleTime: 5 * 60 * 1000,
  });

  // Build daily counts from weekly series by distributing evenly across weekdays
  // Then arrange into a calendar grid
  const { weeks, months } = useMemo(() => {
    if (!data?.series || data.series.length === 0) {
      return { weeks: [], months: [] };
    }

    // Build a map of date -> count
    // Weekly series: each point has a period like "2024-W01"
    // We distribute the count across the 5 weekdays (Mon-Fri get more, Sat-Sun less)
    const dailyCounts = new Map<string, number>();

    for (const point of data.series) {
      // Try parsing period as a date or week
      const date = new Date(point.period);
      if (!isNaN(date.getTime())) {
        // It's a valid date — this is the start of the week
        for (let d = 0; d < 7; d++) {
          const day = new Date(date);
          day.setDate(day.getDate() + d);
          const key = day.toISOString().slice(0, 10);
          const dailyShare = Math.round(point.count / 7);
          dailyCounts.set(key, (dailyCounts.get(key) ?? 0) + (d < 5 ? dailyShare + 1 : dailyShare));
        }
      } else {
        // Try as YYYY-Www format
        const weekMatch = point.period.match(/^(\d{4})-W(\d{2})$/);
        if (weekMatch) {
          const year = parseInt(weekMatch[1]);
          const week = parseInt(weekMatch[2]);
          // Get Monday of that ISO week
          const jan4 = new Date(year, 0, 4);
          const dayOfWeek = jan4.getDay() || 7;
          const monday = new Date(jan4);
          monday.setDate(jan4.getDate() - dayOfWeek + 1 + (week - 1) * 7);
          for (let d = 0; d < 7; d++) {
            const day = new Date(monday);
            day.setDate(monday.getDate() + d);
            const key = day.toISOString().slice(0, 10);
            const dailyShare = Math.round(point.count / 7);
            dailyCounts.set(key, (dailyCounts.get(key) ?? 0) + dailyShare);
          }
        } else {
          // Monthly data — distribute across days of month
          const monthDate = new Date(point.period + "-01");
          if (!isNaN(monthDate.getTime())) {
            const daysInMonth = new Date(
              monthDate.getFullYear(),
              monthDate.getMonth() + 1,
              0,
            ).getDate();
            const dailyShare = Math.round(point.count / daysInMonth);
            for (let d = 0; d < daysInMonth; d++) {
              const day = new Date(monthDate);
              day.setDate(day.getDate() + d);
              const key = day.toISOString().slice(0, 10);
              dailyCounts.set(key, dailyShare);
            }
          }
        }
      }
    }

    if (dailyCounts.size === 0) return { weeks: [], months: [] };

    // Find date range
    const allDates = Array.from(dailyCounts.keys()).sort();
    const startDate = new Date(allDates[0]);
    const endDate = new Date(allDates[allDates.length - 1]);

    // Align to Monday
    const dayOfWeek = startDate.getDay() || 7; // 1=Mon, 7=Sun
    startDate.setDate(startDate.getDate() - (dayOfWeek - 1));

    // Build weeks grid
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

        if (dayDate > endDate && d > 0) {
          week.push(null);
        } else {
          const count = dailyCounts.get(key) ?? 0;
          week.push({ date: dayDate, count, dateStr: key });

          // Track month labels
          if (dayDate.getMonth() !== lastMonth && d === 0) {
            lastMonth = dayDate.getMonth();
            const monthName = dayDate.toLocaleDateString("es-ES", { month: "short" });
            const yearSuffix = dayDate.getFullYear().toString().slice(2);
            monthLabels.push({
              label: `${monthName} '${yearSuffix}`,
              weekIdx: calWeeks.length,
            });
          }
        }
      }

      calWeeks.push({ weekStart, days: week });
      current.setDate(current.getDate() + 7);
    }

    return { weeks: calWeeks, months: monthLabels };
  }, [data]);

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center">
        <p className="text-destructive">
          {t("common.error")}: {(error as Error).message}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Calendario</h1>
        <p className="text-muted-foreground">
          Heatmap de publicaciones por fecha.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <CalendarDays className="h-5 w-5" />
            Densidad de Publicaciones
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

                {/* Grid: rows = days (Mon-Sun), columns = weeks */}
                {DAY_LABELS.map((dayLabel, dayIdx) => (
                  <div key={dayLabel} className="flex items-center">
                    <div className="w-10 shrink-0 text-xs text-muted-foreground text-right pr-2">
                      {dayIdx % 2 === 0 ? dayLabel : ""}
                    </div>
                    {weeks.map((week, weekIdx) => {
                      const cell = week.days[dayIdx];
                      if (!cell) {
                        return (
                          <div
                            key={weekIdx}
                            className="w-3.5 h-3.5 m-[1px] rounded-sm"
                          />
                        );
                      }
                      return (
                        <div
                          key={weekIdx}
                          className={cn(
                            "w-3.5 h-3.5 m-[1px] rounded-sm transition-colors cursor-default",
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
                    <div
                      key={i}
                      className={cn("w-3.5 h-3.5 rounded-sm", c.bg)}
                      title={c.label}
                    />
                  ))}
                  <span className="text-xs text-muted-foreground">Mas</span>
                </div>
              </div>
            </div>
          ) : (
            <p className="py-12 text-center text-muted-foreground">{t("common.no_data")}</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
