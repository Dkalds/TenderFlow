/**
 * Vocabulario compartido de la consola del Radar.
 *
 * Colores y rampas salen de los tokens reales de `globals.css` — bandas de
 * scoring (`--score-*`) y semáforo de urgencia (`--urgency-*`) — para que la
 * consola no invente una segunda paleta paralela a la del sistema de gráficos.
 */

/** Banda de scoring que devuelve el backend (`Caliente|Atractiva|Tibia|Descarte`). */
export const BAND_TOKEN: Record<string, string> = {
  Caliente: "var(--score-hot)",
  Atractiva: "var(--score-warm)",
  Tibia: "var(--score-cold)",
  Descarte: "var(--score-skip)",
};

/** Color de la banda, con caída al gris de «sin puntuar». */
export function bandColor(band: string | null | undefined): string {
  return `hsl(${BAND_TOKEN[band ?? ""] ?? "var(--score-skip)"})`;
}

export function bandColorAlpha(band: string | null | undefined, alpha: number): string {
  return `hsl(${BAND_TOKEN[band ?? ""] ?? "var(--score-skip)"} / ${alpha})`;
}

export interface Urgency {
  /** Color del semáforo, ya resuelto a `hsl(...)`. */
  color: string;
  /** Proporción de la barra, 0–1: cuánto queda de mecha. */
  ratio: number;
}

/**
 * Semáforo de plazo. Los cortes (5 · 12 · 25 días) son los mismos que usa el
 * resto del producto para hablar de urgencia; el color viene de los tokens
 * `--urgency-*`, que ya son rojo → verde y no cruzan la paleta categórica.
 */
export function urgency(days: number | null): Urgency {
  if (days == null) return { color: "hsl(var(--muted-foreground))", ratio: 0 };
  if (days <= 5) return { color: "hsl(var(--urgency-critical))", ratio: 0.96 };
  if (days <= 12) return { color: "hsl(var(--urgency-high))", ratio: 0.74 };
  if (days <= 25) return { color: "hsl(var(--urgency-medium))", ratio: 0.48 };
  return { color: "hsl(var(--urgency-low))", ratio: 0.22 };
}

/** Días naturales hasta una fecha ISO; negativo si ya pasó. */
export function daysLeft(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const target = new Date(iso);
  if (Number.isNaN(target.getTime())) return null;
  const today = new Date();
  const startOfDay = (d: Date) => Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
  return Math.round((startOfDay(target) - startOfDay(today)) / 86400000);
}

/**
 * Importe en la forma corta de la consola: `4,82 M€` / `740K €`. Es la misma
 * lectura que el mock, pensada para una columna tabular estrecha; el importe
 * exacto vive en el inspector.
 */
export function shortEur(value: number | null | undefined): string {
  if (value == null) return "—";
  if (Math.abs(value) >= 1e6) {
    const millions = value / 1e6;
    return `${millions.toFixed(Math.abs(value) >= 1e7 ? 1 : 2).replace(".", ",")} M€`;
  }
  if (Math.abs(value) >= 1000) return `${Math.round(value / 1000)}K €`;
  return `${Math.round(value)} €`;
}

/** Etiquetas presentacionales del desglose de score (mismas que DetailPanel). */
export const DESGLOSE_LABELS: Record<string, string> = {
  importe: "Importe",
  plazo: "Plazo",
  competencia: "Competencia",
  margen: "Margen",
  afinidad: "Afinidad",
  riesgo: "Riesgo",
};
