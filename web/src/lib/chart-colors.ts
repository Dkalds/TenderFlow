/**
 * Single source of truth for chart and status colors.
 *
 * Values reference the CSS custom properties defined in `globals.css`, so
 * light/dark theming and palette tweaks happen in exactly one place. Recharts
 * and inline `style` accept `hsl(var(--token))` strings directly — the browser
 * resolves the variable, so series colors follow the active theme automatically.
 */

import { estadoLabel } from "@/lib/estados";

/** Ordered categorical palette for multi-series charts (10 distinct hues). */
export const CHART_SERIES = [
  "hsl(var(--chart-1))",
  "hsl(var(--chart-2))",
  "hsl(var(--chart-3))",
  "hsl(var(--chart-4))",
  "hsl(var(--chart-5))",
  "hsl(var(--chart-6))",
  "hsl(var(--chart-7))",
  "hsl(var(--chart-8))",
  "hsl(var(--chart-9))",
  "hsl(var(--chart-10))",
] as const;

/** Color for series index `i`, wrapping around the palette. */
export function getSeriesColor(i: number): string {
  const n = CHART_SERIES.length;
  return CHART_SERIES[((i % n) + n) % n];
}

/**
 * La misma paleta como clase de color de texto, para pintar sin `style={{}}`
 * (`scripts/check_inline_styles.py`): un SVG con `fill="currentColor"` o un
 * punto con `bg-current`. Literales enteros para que Tailwind los encuentre.
 */
const CHART_SERIES_TEXTO = [
  "text-[hsl(var(--chart-1))]",
  "text-[hsl(var(--chart-2))]",
  "text-[hsl(var(--chart-3))]",
  "text-[hsl(var(--chart-4))]",
  "text-[hsl(var(--chart-5))]",
  "text-[hsl(var(--chart-6))]",
  "text-[hsl(var(--chart-7))]",
  "text-[hsl(var(--chart-8))]",
  "text-[hsl(var(--chart-9))]",
  "text-[hsl(var(--chart-10))]",
] as const;

/** Clase de color de texto de la serie `i`, con la misma vuelta que `getSeriesColor`. */
export function getSeriesTextClass(i: number): string {
  const n = CHART_SERIES_TEXTO.length;
  return CHART_SERIES_TEXTO[((i % n) + n) % n];
}

/**
 * Tender state -> chart fill color (token-based). Use `getEstadoChartColor`
 * for a safe lookup that falls back to the first series color.
 *
 * Indexada por la etiqueta legible, no por el código PLACSP: `estadoLabel`
 * normaliza antes de buscar (ver `lib/estados.ts` para por qué hacía falta).
 */
export const ESTADO_CHART_COLOR: Record<string, string> = {
  Publicada: "hsl(var(--chart-1))",
  Adjudicada: "hsl(var(--chart-2))",
  Desierta: "hsl(var(--chart-3))",
  "Evaluación": "hsl(var(--chart-4))",
  Anulada: "hsl(var(--chart-5))",
  "En plazo": "hsl(var(--chart-6))",
  Resuelta: "hsl(var(--chart-7))",
  "Anuncio previo": "hsl(var(--chart-9))",
  Creada: "hsl(var(--chart-10))",
  // Estados PSCP canonizados por la migración v91. «Publicación agregada» es
  // el 93% del corpus, así que es la barra que domina la composición del
  // Resumen: darle color propio es lo que la distingue del resto.
  "Publicación agregada": "hsl(var(--chart-8))",
  "En ejecución": "hsl(var(--chart-3))",
  "Consulta preliminar": "hsl(var(--chart-6))",
};

export function getEstadoChartColor(estado: string | null | undefined): string {
  const label = estadoLabel(estado);
  return (label ? ESTADO_CHART_COLOR[label] : undefined) ?? CHART_SERIES[0];
}

/** Urgency semaphore (red -> green ramp) — deadline proximity, gantt bars, alerts. */
export const URGENCY_COLORS = {
  critical: "hsl(var(--urgency-critical))",
  high: "hsl(var(--urgency-high))",
  medium: "hsl(var(--urgency-medium))",
  low: "hsl(var(--urgency-low))",
} as const;
