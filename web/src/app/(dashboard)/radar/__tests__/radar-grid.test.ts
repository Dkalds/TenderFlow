import { describe, expect, it } from "vitest";
import { RADAR_GRID } from "../_components/radar-shared";

/**
 * Presupuesto de la columna de acciones, sin layout: jsdom no mide, así que la
 * medida real vive en `e2e/responsive.spec.ts` (1024 px). Esto fija la
 * aritmética que la justifica, y corre sin backend.
 *
 * Botón de icono 26 px (`md:w-6.5`), hueco 6 (`md:gap-1.5`). «Abrir» a 11 px
 * semibold con `px-2.5` y borde mide ~47 px en Geist.
 */
const ICONO = 26;
const HUECO = 6;
const ABRIR = 47;
const acciones = (iconos: number) => iconos * ICONO + ABRIR + iconos * HUECO;

function columnas(prefijo: "md" | "xl"): string[] {
  const m = RADAR_GRID.match(new RegExp(`(?:^|\\s)${prefijo}:grid-cols-\\[([^\\]]+)\\]`));
  if (!m) throw new Error(`RADAR_GRID no declara ${prefijo}:grid-cols`);
  return m[1].split("_");
}

const px = (col: string) => Number(col.replace(/px$/, ""));
const fijas = (cols: string[]) => cols.filter((c) => c.endsWith("px")).reduce((s, c) => s + px(c), 0);

describe("RADAR_GRID", () => {
  it("entre md y xl la columna de acciones aloja los cuatro botones (con «Ver ficha»)", () => {
    expect(px(columnas("md").at(-1)!)).toBeGreaterThanOrEqual(acciones(3));
  });

  it("a partir de xl aloja los tres de siempre", () => {
    expect(px(columnas("xl").at(-1)!)).toBeGreaterThanOrEqual(acciones(2));
  });

  it("las dos franjas tienen las mismas columnas y el mismo ancho fijo: el título no pierde", () => {
    const md = columnas("md");
    const xl = columnas("xl");
    expect(md).toHaveLength(xl.length);
    expect(md[1]).toBe("1fr");
    expect(xl[1]).toBe("1fr");
    expect(fijas(md)).toBe(fijas(xl));
  });
});
