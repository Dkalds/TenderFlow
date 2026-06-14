"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Branded Recharts tooltip — drop-in for `<Tooltip content={<ChartTooltip ... />} />`.
 *
 * Uses popover surface + token border + layered shadow so every chart speaks
 * the same visual language as the rest of the design system. The default
 * Recharts tooltip is also globally themed in `globals.css`, but this
 * component is the explicit choice for tooltips that need custom rows,
 * formatters, or labels.
 */
export interface ChartTooltipRow {
  /** Series label (e.g. "Importe") */
  name?: React.ReactNode;
  /** Pre-formatted value */
  value: React.ReactNode;
  /** Color swatch (hex / hsl / token). Optional. */
  color?: string;
}

export interface ChartTooltipProps {
  /** Injected by Recharts */
  active?: boolean;
  /** Injected by Recharts */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  payload?: any[];
  /** Injected by Recharts */
  label?: React.ReactNode;
  /** Override the label rendered at the top */
  labelFormatter?: (label: React.ReactNode) => React.ReactNode;
  /** Format every row. Receives raw value + the recharts entry. */
  formatter?: (
    value: number | string,
    name: string,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    entry: any,
  ) => ChartTooltipRow | [React.ReactNode, React.ReactNode] | string;
  /** Hide the series swatch */
  hideSwatch?: boolean;
  className?: string;
}

export function ChartTooltip({
  active,
  payload,
  label,
  labelFormatter,
  formatter,
  hideSwatch = false,
  className,
}: ChartTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;

  const rows: ChartTooltipRow[] = payload.map((entry) => {
    const rawName: string = entry?.name ?? entry?.dataKey ?? "";
    const rawValue: number | string = entry?.value ?? "";
    const fallbackColor: string | undefined = entry?.color ?? entry?.fill;

    if (!formatter) {
      return { name: rawName, value: String(rawValue), color: fallbackColor };
    }
    const result = formatter(rawValue, rawName, entry);
    if (typeof result === "string") {
      return { name: rawName, value: result, color: fallbackColor };
    }
    if (Array.isArray(result)) {
      return { name: result[1], value: result[0], color: fallbackColor };
    }
    return { color: fallbackColor, ...result };
  });

  const renderedLabel = labelFormatter ? labelFormatter(label) : label;

  return (
    <div
      role="tooltip"
      className={cn(
        "min-w-[10rem] rounded-md border border-border bg-popover px-3 py-2",
        "text-xs text-popover-foreground shadow-md",
        "tf-tnum",
        className,
      )}
    >
      {renderedLabel != null && renderedLabel !== "" && (
        <p className="mb-1 text-xs font-semibold text-foreground">{renderedLabel}</p>
      )}
      <ul className="space-y-0.5">
        {rows.map((row, i) => (
          <li key={i} className="flex items-center gap-2">
            {!hideSwatch && row.color && (
              <span
                aria-hidden
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: row.color }}
              />
            )}
            {row.name != null && row.name !== "" && (
              <span className="text-muted-foreground">{row.name}:</span>
            )}
            <span className="ml-auto font-medium text-foreground">{row.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
