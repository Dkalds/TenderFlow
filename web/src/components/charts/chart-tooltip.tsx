"use client";

import type * as React from "react";
import type { TooltipPayloadEntry } from "recharts";
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
/**
 * La caja de todo tooltip de gráfico: superficie de popover, borde de token,
 * `shadow-md` (capa flotante) y texto a 12 px con cifras tabulares. La usan
 * también los tooltips hechos a medida (`content={...}`), para que ninguno
 * tenga su propio tamaño de letra.
 */
export const CAJA_TOOLTIP =
  "tf-tnum min-w-[10rem] rounded-md border border-border bg-popover px-3 py-2 text-tf-meta text-popover-foreground shadow-md";

export interface ChartTooltipRow {
  /** Series label (e.g. "Importe") */
  name?: React.ReactNode;
  /** Pre-formatted value */
  value: React.ReactNode;
  /** Color swatch (hex / hsl / token). Optional. */
  color?: string;
}

/**
 * Lo que el tooltip lee de cada entrada de Recharts (`TooltipPayloadEntry`).
 * Todo opcional: también la pintan tooltips hechos a mano con objetos sueltos
 * (`waterfall-chart.tsx`), que no traen el `graphicalItemId` de Recharts.
 */
export type ChartTooltipEntry = Partial<
  Pick<TooltipPayloadEntry, "name" | "value" | "dataKey" | "color" | "fill" | "payload">
>;

/** El valor de una entrada como texto o número; un rango (`[min, max]`) se lee «min–max». */
function valorDe(valor: ChartTooltipEntry["value"]): number | string {
  if (valor == null) return "";
  return typeof valor === "number" || typeof valor === "string" ? valor : valor.join("–");
}

export interface ChartTooltipProps {
  /** Injected by Recharts */
  active?: boolean;
  /** Injected by Recharts */
  payload?: readonly ChartTooltipEntry[];
  /** Injected by Recharts */
  label?: React.ReactNode;
  /** Override the label rendered at the top */
  labelFormatter?: (label: React.ReactNode) => React.ReactNode;
  /** Format every row. Receives raw value + the recharts entry. */
  formatter?: (
    value: number | string,
    name: string,
    entry: ChartTooltipEntry,
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
    const rawName = String(entry.name ?? (typeof entry.dataKey === "function" ? "" : (entry.dataKey ?? "")));
    const rawValue = valorDe(entry.value);
    const fallbackColor = entry.color ?? entry.fill;

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
      className={cn(CAJA_TOOLTIP, className)}
    >
      {renderedLabel != null && renderedLabel !== "" && (
        <p className="mb-1 font-semibold text-foreground">{renderedLabel}</p>
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
