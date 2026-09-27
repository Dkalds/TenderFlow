/**
 * `lib/marca.ts` es la única copia importable de la marca. Estos tests fijan
 * que no derive de las dos copias que no pueden importarla: los tokens de
 * `globals.css` (de donde salen sus hex) y `public/favicon.svg` (un estático).
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it, expect } from "vitest";
import {
  MARCA_HEX,
  MARCA_NOMBRE,
  TF_MARK_ESCALA,
  TF_MARK_PATHS,
  TF_MARK_RADIO,
  TF_MARK_STROKE,
  TF_MARK_VIEWBOX,
} from "@/lib/marca";

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const CSS = readFileSync(path.resolve(AQUI, "../../app/globals.css"), "utf8");
const FAVICON = readFileSync(path.resolve(AQUI, "../../../public/favicon.svg"), "utf8");

/** Valor HSL («26 88% 62%») de un token dentro del bloque `:root` o `.dark`. */
function token(bloque: ":root" | ".dark", nombre: string): string {
  const inicio = CSS.indexOf(`  ${bloque} {`);
  expect(inicio, `bloque ${bloque} en globals.css`).toBeGreaterThanOrEqual(0);
  const cuerpo = CSS.slice(inicio, CSS.indexOf("\n  }", inicio));
  const valor = cuerpo.match(new RegExp(`--${nombre}:\\s*([^;]+);`))?.[1];
  expect(valor, `--${nombre} en ${bloque}`).toBeDefined();
  return valor!.trim();
}

/** HSL de la hoja («26 88% 62%») a hex en mayúsculas, como `MARCA_HEX`. */
function hslAHex(hsl: string): string {
  const [h, s, l] = hsl.replace(/%/g, "").split(/\s+/).map(Number);
  const sat = s / 100;
  const lum = l / 100;
  const a = sat * Math.min(lum, 1 - lum);
  const canal = (n: number) => {
    const k = (n + h / 30) % 12;
    const v = lum - a * Math.max(-1, Math.min(k - 3, Math.min(9 - k, 1)));
    return Math.round(v * 255)
      .toString(16)
      .padStart(2, "0");
  };
  return `#${canal(0)}${canal(8)}${canal(4)}`.toUpperCase();
}

describe("trazo del monograma", () => {
  it("son tres trazos (barra, asta de la T y brazo de la F) en una caja de 24", () => {
    expect(TF_MARK_VIEWBOX).toBe("0 0 24 24");
    expect(TF_MARK_PATHS).toEqual(["M3.5 6 H20.5", "M12 6 V19", "M12 12 H18.5"]);
    expect(TF_MARK_STROKE).toBeGreaterThan(0);
  });

  it("el favicon, que no puede importar el módulo, dibuja el mismo trazo con el mismo grosor", () => {
    for (const d of TF_MARK_PATHS) expect(FAVICON).toContain(`d="${d}"`);
    expect(FAVICON).toContain(`stroke-width="${TF_MARK_STROKE}"`);
    expect(FAVICON).toContain(`fill="${MARCA_HEX.naranjaFavicon}"`);
  });

  it("las proporciones de la caja son fracciones del lado", () => {
    for (const p of [TF_MARK_ESCALA, TF_MARK_RADIO]) {
      expect(p).toBeGreaterThan(0);
      expect(p).toBeLessThan(1);
    }
  });
});

describe("MARCA_HEX", () => {
  it("son hex de seis cifras", () => {
    for (const hex of Object.values(MARCA_HEX)) expect(hex).toMatch(/^#[0-9A-F]{6}$/);
  });

  it("los colores que se pintan fuera del navegador son los de los tokens de la hoja", () => {
    expect(MARCA_HEX.naranja).toBe(hslAHex(token(".dark", "primary")));
    expect(MARCA_HEX.oxido).toBe(hslAHex(token(":root", "primary")));
    expect(MARCA_HEX.tinta).toBe(hslAHex(token(".dark", "background")));
    expect(MARCA_HEX.papel).toBe(hslAHex(token(".dark", "foreground")));
  });

  it("el nombre del producto se escribe una sola vez", () => {
    expect(MARCA_NOMBRE).toBe("TenderFlow");
  });
});
