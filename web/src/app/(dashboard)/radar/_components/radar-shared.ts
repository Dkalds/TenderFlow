/**
 * Vocabulario compartido de la consola del Radar.
 *
 * Colores y rampas salen de los tokens reales de `globals.css` — bandas de
 * scoring (`--score-*`) y semáforo de urgencia (`--urgency-*`) — para que la
 * consola no invente una segunda paleta paralela a la del sistema de gráficos.
 */

/**
 * Rejilla de la tabla — solo a partir de `md`. Por debajo no hay rejilla: la
 * fila es una ficha en columna (ver `radar-fila.tsx`), y la cabecera de columnas
 * desaparece porque no habría columnas que rotular.
 *
 * Vive aquí y no en uno de los dos componentes que la usan porque cabecera y
 * fila tienen que compartir exactamente el mismo reparto: si divergen, los
 * rótulos dejan de caer sobre sus datos.
 *
 * La columna de acciones mide 116 px (antes 108, que se quitan de Importe):
 * descartar + seguir (26 px cada uno, `gap` de 6) + «Abrir» suman ~113 px. En
 * 108 no cabían, y como los botones de icono podían encogerse, «Descartar»
 * quedaba por debajo de los 24 px de WCAG 2.5.8 (axe `target-size`, /radar).
 * Ahora los botones de icono son `flex-none` y la columna los aloja enteros.
 *
 * **Entre `md` y `xl` hay un cuarto botón**: «Ver ficha», porque ahí el
 * inspector es un `Sheet` y no hay otro disparador (`conFicha`, que sale de
 * `useModoInspector()` con los mismos 768/1280 que `md`/`xl`). Son 3 × 26 +
 * «Abrir» + 3 huecos de 6 ≈ 143 px: en 116 los botones no encogen (son
 * `flex-none`), así que la fila desbordaba por la izquierda —`justify-end`—
 * y se montaba sobre Plazo. El E2E de accesibilidad corre a 1280, donde solo
 * hay tres, y no lo veía. En esa franja la columna pasa a 148 px y los 32 salen
 * de Órgano, que ya trunca, no de Licitación: el `1fr` del título queda igual.
 * A partir de `xl` vuelve el reparto de siempre.
 * `responsive.spec.ts` lo mide a 1024 px.
 */
export const RADAR_GRID =
  "md:grid-cols-[46px_1fr_144px_132px_100px_96px_148px] xl:grid-cols-[46px_1fr_176px_132px_100px_96px_116px] md:gap-3 md:px-3.5";

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
  senal_tecnica: "Señal técnica",
  riesgo: "Riesgo",
};
