/**
 * Vocabulario compartido de la consola del Radar.
 *
 * Colores y rampas salen de los tokens reales de `globals.css` — bandas de
 * scoring (`--score-*`) y semáforo de urgencia (`--urgency-*`) — para que la
 * consola no invente una segunda paleta paralela a la del sistema de gráficos.
 *
 * Se entregan como **clases** y no como colores sueltos para un `style`: cada
 * estilo en línea ata `style-src` a `'unsafe-inline'`
 * (`scripts/check_inline_styles.py`). Las cadenas van enteras y literales,
 * porque el JIT de Tailwind solo ve lo que está escrito.
 */

/**
 * Rejilla de la tabla — solo a partir de `lg`. Por debajo no hay rejilla: la
 * fila es una ficha en columna (ver `radar-fila.tsx`), y la cabecera de columnas
 * desaparece porque no habría columnas que rotular.
 *
 * Fue `md` hasta el 2026-09-27. Las columnas fijas y los huecos suman ~766 px
 * antes del título; a 768 px de pantalla, con el rail de 84, quedan 684, y
 * `#main-content` desbordaba 133 px en horizontal. A 1024 quedan 940, menos los
 * 10 de la barra de la lista: el título se lleva ~164 (medido). El umbral de
 * JS (`MQ_TABLA_RADAR`) tiene que ser el mismo `lg`, en rem como el de
 * Tailwind, y `radar-grid.test.ts` hace la cuenta.
 *
 * Vive aquí y no en uno de los dos componentes que la usan porque cabecera y
 * fila tienen que compartir exactamente el mismo reparto: si divergen, los
 * rótulos dejan de caer sobre sus datos.
 *
 * La columna del score mide 52 px: debajo de la cifra va la banda en frase y a
 * 11 px («Atractiva», la más ancha, son ~47 px en Geist), no el código en
 * versal de 8 px que cabía en 46. Los 6 px salen de Órgano, que ya trunca, no
 * de Licitación: el `1fr` del título queda igual.
 *
 * La columna de acciones mide 116 px (antes 108, que se quitan de Importe):
 * descartar + seguir (26 px cada uno, `gap` de 6) + «Abrir» suman ~113 px. En
 * 108 no cabían, y como los botones de icono podían encogerse, «Descartar»
 * quedaba por debajo de los 24 px de WCAG 2.5.8 (axe `target-size`, /radar).
 * Ahora los botones de icono son `flex-none` y la columna los aloja enteros.
 *
 * **Entre `lg` y `xl` hay un cuarto botón**: «Ver ficha», porque ahí el
 * inspector es un `Sheet` y no hay otro disparador (`conFicha`, que sale de
 * `useModoInspector()`: `Sheet` desde 768 y anclado desde 1280; entre 768 y
 * 1024 el botón va en la ficha, no en la tabla). Son 3 × 26 +
 * «Abrir» + 3 huecos de 6 ≈ 143 px: en 116 los botones no encogen (son
 * `flex-none`), así que la fila desbordaba por la izquierda —`justify-end`—
 * y se montaba sobre Plazo. El E2E de accesibilidad corre a 1280, donde solo
 * hay tres, y no lo veía. En esa franja la columna pasa a 148 px y los 32 salen
 * de Órgano, que ya trunca, no de Licitación: el `1fr` del título queda igual.
 * A partir de `xl` vuelve el reparto de siempre.
 * `responsive.spec.ts` lo mide a 1024 px.
 */
export const RADAR_GRID =
  "lg:grid-cols-[52px_1fr_138px_132px_100px_96px_148px] xl:grid-cols-[52px_1fr_170px_132px_100px_96px_116px] lg:gap-3 lg:px-3.5";

/** Banda de scoring que devuelve el backend (`Caliente|Atractiva|Tibia|Descarte`). */
export const BAND_TOKEN: Record<string, string> = {
  Caliente: "var(--score-hot)",
  Atractiva: "var(--score-warm)",
  Tibia: "var(--score-cold)",
  Descarte: "var(--score-skip)",
};

/**
 * Color de la banda, con caída al gris de «sin puntuar». Para quien necesita
 * el color como valor (un gráfico); en JSX, `claseTextoBanda`/`claseFondoBanda`.
 */
export function bandColor(band: string | null | undefined): string {
  return `hsl(${BAND_TOKEN[band ?? ""] ?? "var(--score-skip)"})`;
}

const TEXTO_BANDA: Record<string, string> = {
  Caliente: "text-[hsl(var(--score-hot))]",
  Atractiva: "text-[hsl(var(--score-warm))]",
  Tibia: "text-[hsl(var(--score-cold))]",
  Descarte: "text-[hsl(var(--score-skip))]",
};

const FONDO_BANDA: Record<string, string> = {
  Caliente: "bg-[hsl(var(--score-hot))]",
  Atractiva: "bg-[hsl(var(--score-warm))]",
  Tibia: "bg-[hsl(var(--score-cold))]",
  Descarte: "bg-[hsl(var(--score-skip))]",
};

/** Clase de texto en el color de la banda (la cifra del score). */
export function claseTextoBanda(band: string | null | undefined): string {
  return TEXTO_BANDA[band ?? ""] ?? TEXTO_BANDA.Descarte;
}

/** Clase de fondo en el color de la banda (la marca lateral de la fila activa). */
export function claseFondoBanda(band: string | null | undefined): string {
  return FONDO_BANDA[band ?? ""] ?? FONDO_BANDA.Descarte;
}

export interface Urgency {
  /** Clase de texto del semáforo (la cifra de días). */
  texto: string;
  /** Clase de fondo del semáforo (la mecha). */
  fondo: string;
  /** Ancho de la mecha: cuánto queda. Cuatro tramos, así que una clase. */
  ancho: string;
}

/**
 * Semáforo de plazo. Los cortes (5 · 12 · 25 días) son los mismos que usa el
 * resto del producto para hablar de urgencia; el color viene de los tokens
 * `--urgency-*`, que ya son rojo → verde y no cruzan la paleta categórica.
 */
export function urgency(days: number | null): Urgency {
  if (days == null) return { texto: "text-muted-foreground", fondo: "bg-muted-foreground", ancho: "w-0" };
  if (days <= 5) {
    return {
      texto: "text-[hsl(var(--urgency-critical))]",
      fondo: "bg-[hsl(var(--urgency-critical))]",
      ancho: "w-[96%]",
    };
  }
  if (days <= 12) {
    return {
      texto: "text-[hsl(var(--urgency-high))]",
      fondo: "bg-[hsl(var(--urgency-high))]",
      ancho: "w-[74%]",
    };
  }
  if (days <= 25) {
    return {
      texto: "text-[hsl(var(--urgency-medium))]",
      fondo: "bg-[hsl(var(--urgency-medium))]",
      ancho: "w-[48%]",
    };
  }
  return {
    texto: "text-[hsl(var(--urgency-low))]",
    fondo: "bg-[hsl(var(--urgency-low))]",
    ancho: "w-[22%]",
  };
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
