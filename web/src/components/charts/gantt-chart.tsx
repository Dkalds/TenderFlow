"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/utils";

interface GanttItem {
  id: string;
  label: string;
  start: string;
  end: string;
  color?: string;
  progress?: number;
}

interface GanttChartProps {
  items: GanttItem[];
  height?: number;
  className?: string;
  onItemClick?: (id: string) => void;
}

export function GanttChart({ items, height, className, onItemClick }: GanttChartProps) {
  const { minDate, months, totalMs } = React.useMemo(() => {
    if (items.length === 0) {
      // eslint-disable-next-line react-hooks/purity
      const now = Date.now();
      return { minDate: now, maxDate: now + 1, months: [] as Date[], totalMs: 1 };
    }
    const starts = items.map((i) => new Date(i.start).getTime());
    const ends = items.map((i) => new Date(i.end).getTime());
    const min = Math.min(...starts);
    const max = Math.max(...ends);
    const total = max - min || 1;

    const monthList: Date[] = [];
    const d = new Date(min);
    d.setDate(1);
    while (d.getTime() <= max) {
      monthList.push(new Date(d));
      d.setMonth(d.getMonth() + 1);
    }

    return { minDate: min, maxDate: max, months: monthList, totalMs: total };
  }, [items]);

  const rowHeight = 32;
  const headerHeight = 28;
  const labelWidth = 180;
  const [tooltip, setTooltip] = React.useState<{ x: number; y: number; item: GanttItem } | null>(null);

  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground text-center py-8">Sin tareas disponibles</p>;
  }

  return (
    <div aria-label="Diagrama de Gantt" className={cn("relative w-full overflow-auto border border-border rounded-md", className)} style={{ maxHeight: height }}>
      {/* Header */}
      <div className="sticky top-0 z-10 flex bg-muted" style={{ height: headerHeight }}>
        <div className="shrink-0 border-r border-border px-2 text-xs font-medium flex items-center text-muted-foreground" style={{ width: labelWidth }}>
          Tarea
        </div>
        <div className="relative flex-1">
          {months.map((m, i) => {
            const left = ((m.getTime() - minDate) / totalMs) * 100;
            return (
              <span
                key={i}
                className="absolute top-0 flex h-full items-center text-xs text-muted-foreground"
                style={{ left: `${left}%` }}
              >
                {m.toLocaleDateString("es-ES", { month: "short", year: "2-digit" })}
              </span>
            );
          })}
        </div>
      </div>

      {/* Rows */}
      {items.map((item) => {
        const startMs = new Date(item.start).getTime();
        const endMs = new Date(item.end).getTime();
        const left = ((startMs - minDate) / totalMs) * 100;
        const width = ((endMs - startMs) / totalMs) * 100;

        return (
          <div
            key={item.id}
            className="flex items-center border-b border-border last:border-b-0"
            style={{ height: rowHeight }}
          >
            <div
              className="shrink-0 truncate border-r border-border px-2 text-xs"
              style={{ width: labelWidth }}
              title={item.label}
            >
              {item.label}
            </div>
            <div className="relative flex-1 h-full flex items-center">
              <div
                className="absolute h-6 rounded cursor-pointer transition-opacity hover:opacity-80"
                style={{
                  left: `${left}%`,
                  width: `${Math.max(width, 0.5)}%`,
                  backgroundColor: item.color ?? "hsl(var(--primary))",
                }}
                tabIndex={0}
                role="button"
                aria-label={item.label}
                onClick={() => onItemClick?.(item.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onItemClick?.(item.id);
                  }
                }}
                onMouseEnter={(e) => {
                  const rect = e.currentTarget.getBoundingClientRect();
                  const parentRect = e.currentTarget.closest(".relative")?.getBoundingClientRect();
                  setTooltip({
                    x: rect.left - (parentRect?.left ?? 0) + rect.width / 2,
                    y: rect.top - (parentRect?.top ?? 0) - 4,
                    item,
                  });
                }}
                onMouseLeave={() => setTooltip(null)}
              >
                {item.progress != null && (
                  <div
                    className="h-full rounded opacity-40 bg-white"
                    style={{ width: `${100 - item.progress}%`, marginLeft: "auto" }}
                  />
                )}
              </div>
            </div>
          </div>
        );
      })}

      {/* Tooltip */}
      {tooltip && (
        <div
          role="tooltip"
          className="absolute z-20 rounded border border-border bg-popover px-2 py-1 text-xs text-popover-foreground shadow pointer-events-none -translate-x-1/2 -translate-y-full"
          style={{ left: labelWidth + tooltip.x, top: headerHeight + tooltip.y }}
        >
          <p className="font-medium">{tooltip.item.label}</p>
          <p>{formatDate(tooltip.item.start)} — {formatDate(tooltip.item.end)}</p>
          {tooltip.item.progress != null && <p>Progreso: {tooltip.item.progress}%</p>}
        </div>
      )}
    </div>
  );
}
