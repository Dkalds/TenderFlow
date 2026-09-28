import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { RAIL_WIDTH } from "@/components/layout/console-rail";
import { RADAR_GRID } from "../_components/radar-shared";
import { MQ_INSPECTOR_ANCLADO, MQ_INSPECTOR_SHEET, MQ_TABLA_RADAR } from "../_hooks/use-media-query";

/**
 * Presupuesto de la columna de acciones y del ancho de la tabla, sin layout:
 * jsdom no mide, así que la medida real vive en `e2e/responsive.spec.ts` (768 y
 * 1024 px). Esto fija la aritmética que la justifica, y corre sin backend.
 *
 * Botón de icono 26 px (`lg:w-6.5`), hueco 6 (`lg:gap-1.5`). «Abrir» a 11 px
 * semibold con `px-2.5` y borde mide ~47 px en Geist.
 */
const ICONO = 26;
const HUECO = 6;
const ABRIR = 47;
const acciones = (iconos: number) => iconos * ICONO + ABRIR + iconos * HUECO;

/** `lg:gap-3` entre columnas y `lg:px-3.5` a cada lado de la fila. */
const HUECO_COLUMNAS = 12;
const MARGEN_FILA = 2 * 14;
/**
 * La lista (`radar-lista.tsx`) es `overflow-y-auto` y con 24 filas saca su barra:
 * 10 px en Chromium (`::-webkit-scrollbar` de `globals.css`). Medido a 1024 px,
 * el título se quedaba en 164 px, no en los 174 que salen sin contarla.
 */
const BARRA_SCROLL = 10;
/**
 * Lo mínimo que tiene que quedarle al título (`1fr`): unos 17 caracteres a
 * 13 px. El título entero lo repite el inspector para la fila activa.
 */
const TITULO_MINIMO = 120;
/** La columna del inspector anclado (`w-[432px]` en radar-inspector-panel.tsx), desde `xl`. */
const INSPECTOR_ANCLADO = 432;
/** La letra por defecto del navegador, contra la que se resuelve el rem de una media query. */
const LETRA_BASE = 16;

function columnas(prefijo: "lg" | "xl"): string[] {
  const m = RADAR_GRID.match(new RegExp(`(?:^|\\s)${prefijo}:grid-cols-\\[([^\\]]+)\\]`));
  if (!m) throw new Error(`RADAR_GRID no declara ${prefijo}:grid-cols`);
  return m[1].split("_");
}

const px = (col: string) => Number(col.replace(/px$/, ""));
const fijas = (cols: string[]) => cols.filter((c) => c.endsWith("px")).reduce((s, c) => s + px(c), 0);
const anchoSinTitulo = (cols: string[]) =>
  fijas(cols) + (cols.length - 1) * HUECO_COLUMNAS + MARGEN_FILA + BARRA_SCROLL;

/** El valor de `min-width` de una media query, tal cual (`64rem`). */
const minWidth = (query: string) => /min-width:\s*([^)]+)\)/.exec(query)![1].trim();
const aPx = (valor: string) => Number.parseFloat(valor) * (valor.endsWith("rem") ? LETRA_BASE : 1);

/** Los breakpoints que Tailwind v4 genera (`--breakpoint-md: 48rem`…). */
function breakpointDeTailwind(nombre: "md" | "lg" | "xl"): string {
  const tema = readFileSync(join(process.cwd(), "node_modules/tailwindcss/theme.css"), "utf8");
  const m = new RegExp(`--breakpoint-${nombre}:\\s*([^;]+);`).exec(tema);
  if (!m) throw new Error(`tailwindcss/theme.css no declara --breakpoint-${nombre}`);
  return m[1].trim();
}

describe("RADAR_GRID", () => {
  it("entre lg y xl la columna de acciones aloja los cuatro botones (con «Ver ficha»)", () => {
    expect(px(columnas("lg").at(-1)!)).toBeGreaterThanOrEqual(acciones(3));
  });

  it("a partir de xl aloja los tres de siempre", () => {
    expect(px(columnas("xl").at(-1)!)).toBeGreaterThanOrEqual(acciones(2));
  });

  it("desde xl la rejilla es la de lg sin la columna de Tecnología", () => {
    // Con el inspector anclado no caben siete columnas: Tecnología pasa a la
    // línea del título (`radar-fila.tsx`) y su rótulo se oculta en la cabecera.
    const lg = columnas("lg");
    const xl = columnas("xl");
    expect(xl).toHaveLength(lg.length - 1);
    expect(lg[1]).toBe("1fr");
    expect(xl[1]).toBe("1fr");
  });

  it("a 1280, con el rail y el inspector anclado, al título le queda sitio", () => {
    // El E2E corre a 1280: con siete columnas el título medía 0 px y no se veía.
    const disponible = aPx(minWidth(MQ_INSPECTOR_ANCLADO)) - RAIL_WIDTH - INSPECTOR_ANCLADO;
    expect(disponible - anchoSinTitulo(columnas("xl"))).toBeGreaterThanOrEqual(TITULO_MINIMO);
  });

  it("la tabla empieza donde cabe con el rail y la barra de la lista", () => {
    expect(RADAR_GRID).not.toMatch(/(?:^|\s)md:/);
    const disponible = aPx(minWidth(MQ_TABLA_RADAR)) - RAIL_WIDTH;
    expect(disponible - anchoSinTitulo(columnas("lg"))).toBeGreaterThanOrEqual(TITULO_MINIMO);
  });

  it("a 768 px no cabría: por eso ahí va la ficha", () => {
    // La cuenta que dejó `#main-content` desbordando 133 px: si alguien baja el
    // umbral a `md` sin estrechar la rejilla, esto lo dice antes que el E2E.
    expect(anchoSinTitulo(columnas("lg"))).toBeGreaterThan(768 - RAIL_WIDTH);
  });
});

describe("umbrales de JS frente a los de Tailwind", () => {
  // De los umbrales de JS sale el `inert` de las acciones ocultas y el modo del
  // inspector; de los de Tailwind, lo que se pinta. Si no son el mismo valor en
  // la misma unidad —el rem de una media query sigue la letra del navegador, el
  // px no—, entre los dos quedan fichas visibles con las acciones `inert`, o
  // filas de tabla con acciones ocultas pero enfocables.
  it("la tabla del Radar empieza en el `lg` de Tailwind", () => {
    expect(minWidth(MQ_TABLA_RADAR)).toBe(breakpointDeTailwind("lg"));
  });

  it("el inspector es `Sheet` desde `md` y va anclado desde `xl`", () => {
    expect(minWidth(MQ_INSPECTOR_SHEET)).toBe(breakpointDeTailwind("md"));
    expect(minWidth(MQ_INSPECTOR_ANCLADO)).toBe(breakpointDeTailwind("xl"));
  });
});
