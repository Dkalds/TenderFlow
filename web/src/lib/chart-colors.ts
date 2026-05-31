/**
 * Single source of truth for chart and status colors.
 *
 * Values reference the CSS custom properties defined in `globals.css`, so
 * light/dark theming and palette tweaks happen in exactly one place. Recharts
 * and inline `style` accept `hsl(var(--token))` strings directly — the browser
 * resolves the variable, so series colors follow the active theme automatically.
 */

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
 * Tender state -> chart fill color (token-based). Use `getEstadoChartColor`
 * for a safe lookup that falls back to the first series color.
 */
export const ESTADO_CHART_COLOR: Record<string, string> = {
  Publicada: "hsl(var(--chart-1))",
  Adjudicada: "hsl(var(--chart-2))",
  Desierta: "hsl(var(--chart-3))",
  Anulada: "hsl(var(--chart-5))",
  "En plazo": "hsl(var(--chart-6))",
  Resuelta: "hsl(var(--chart-7))",
};

export function getEstadoChartColor(estado: string | null | undefined): string {
  return (estado ? ESTADO_CHART_COLOR[estado] : undefined) ?? CHART_SERIES[0];
}

/** Scoring band -> score-band token color. */
export const SCORE_COLOR = {
  hot: "hsl(var(--score-hot))",
  warm: "hsl(var(--score-warm))",
  cold: "hsl(var(--score-cold))",
  skip: "hsl(var(--score-skip))",
} as const;

export type ScoreBand = keyof typeof SCORE_COLOR;

/** Spanish band label -> score token key. */
export const BAND_TO_SCORE: Record<string, ScoreBand> = {
  Caliente: "hot",
  Atractiva: "warm",
  Tibia: "cold",
  Descarte: "skip",
};

export function getBandColor(band: string | null | undefined): string {
  const key = band ? BAND_TO_SCORE[band] : undefined;
  return key ? SCORE_COLOR[key] : SCORE_COLOR.skip;
}
