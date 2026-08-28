/**
 * Contraste WCAG de los tokens de color, calculado sobre `globals.css`.
 *
 * La paleta de TenderFlow se diseñó mirando el tema oscuro, donde los mismos
 * HSL dan 7-12:1 sobre el fondo casi negro. Al aplicarlos al tema claro varios
 * quedaban en 2,9-3,4:1 — y no eran decorativos: `--warning` rotula los avisos
 * de calidad del dato, `--score-warm` la banda media del score y `--urgency-*`
 * el semáforo de plazos. Texto informativo por debajo de 4,5:1 (WCAG 1.4.3) y
 * un color de serie por debajo de 3:1 (1.4.11).
 *
 * Corregirlo una vez no sirve de nada si el siguiente retoque de paleta lo
 * deshace, así que este test no comprueba valores literales: **lee los HSL del
 * propio `globals.css`, los convierte a sRGB y recalcula la luminancia
 * relativa**. Aclarar un token vuelve a poner el test en rojo con el ratio
 * exacto en el mensaje, sea cual sea el HSL nuevo. Se comprueban los dos temas
 * (`:root` y `.dark`) porque la regresión puede entrar por cualquiera.
 *
 * La superficie de referencia es `--card`: estos tokens se pintan como texto
 * (`text-warning`, `style={{ color: bandColor(...) }}`) dentro de tarjetas,
 * tablas y listas, nunca como relleno sólido — no hay un solo `bg-warning`
 * opaco en el árbol. El fondo de página se comprueba aparte para la rampa
 * corregida, por ser la superficie opaca más oscura del tema claro.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, it, expect } from "vitest";

const CSS = readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../app/globals.css"), "utf8");

/** Umbrales de la norma: 1.4.3 para texto, 1.4.11 para objetos gráficos. */
const AA_TEXTO = 4.5;
const AA_GRAFICO = 3;

type Rgb = readonly [number, number, number];

/**
 * HSL -> sRGB en el rango 0-1. Implementación directa de la fórmula de CSS
 * Color 4; no se usa el navegador (jsdom no calcula color computado sobre
 * variables) ni una librería, porque el cálculo es la mitad de lo que este
 * test tiene que garantizar.
 */
function hslToRgb(h: number, s: number, l: number): Rgb {
  const sat = s / 100;
  const lig = l / 100;
  const a = sat * Math.min(lig, 1 - lig);
  const canal = (n: number): number => {
    const k = (n + h / 30) % 12;
    return lig - a * Math.max(-1, Math.min(k - 3, Math.min(9 - k, 1)));
  };
  return [canal(0), canal(8), canal(4)];
}

/** Luminancia relativa (WCAG 2.x §relative luminance), con el gamma de sRGB. */
function luminanciaRelativa([r, g, b]: Rgb): number {
  const lineal = (v: number): number => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lineal(r) + 0.7152 * lineal(g) + 0.0722 * lineal(b);
}

/** Ratio de contraste (L1 + 0,05) / (L2 + 0,05); va de 1 a 21. */
function ratioContraste(a: Rgb, b: Rgb): number {
  const la = luminanciaRelativa(a);
  const lb = luminanciaRelativa(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/**
 * Devuelve el cuerpo del bloque `selector { ... }`. Los comentarios se quitan
 * antes: la nota que documenta los ratios dentro de `:root` contiene líneas
 * con pinta de declaración y envenenaría el parseo.
 */
function bloque(selector: string): string {
  const sinComentarios = CSS.replace(/\/\*[\s\S]*?\*\//g, "");
  const marca = new RegExp(`${selector}\\s*\\{([^}]*)\\}`);
  const encontrado = marca.exec(sinComentarios);
  if (!encontrado) throw new Error(`No se encontró el bloque de tokens \`${selector}\` en globals.css`);
  return encontrado[1];
}

/**
 * Tokens `--x: <h> <s>% <l>%` del bloque. Se descarta a propósito todo lo que
 * no sea un HSL opaco: `--radius`, las sombras y los tokens con alfa
 * (`--border`, `--input`), que no tienen un ratio definido por sí solos.
 */
function tokensHsl(selector: string): ReadonlyMap<string, Rgb> {
  const mapa = new Map<string, Rgb>();
  const declaracion = /--([\w-]+)\s*:\s*([^;]+);/g;
  let m: RegExpExecArray | null;
  while ((m = declaracion.exec(bloque(selector))) !== null) {
    const hsl = /^(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)%\s+(\d+(?:\.\d+)?)%$/.exec(m[2].trim());
    if (hsl) mapa.set(m[1], hslToRgb(Number(hsl[1]), Number(hsl[2]), Number(hsl[3])));
  }
  return mapa;
}

const TEMAS = {
  claro: tokensHsl(":root"),
  oscuro: tokensHsl("\\.dark"),
} as const;

type Tema = keyof typeof TEMAS;

function color(tema: Tema, token: string): Rgb {
  const rgb = TEMAS[tema].get(token);
  if (!rgb) throw new Error(`El token --${token} no existe (o no es un HSL opaco) en el tema ${tema}`);
  return rgb;
}

function ratio(tema: Tema, token: string, superficie: string): number {
  return ratioContraste(color(tema, token), color(tema, superficie));
}

/**
 * Tokens que se renderizan como texto sobre `--card`. La lista es explícita y
 * no derivada del fichero: añadir un token de color nuevo obliga a decidir
 * conscientemente si es texto (4,5:1), objeto gráfico (3:1) o superficie.
 */
const TEXTO_SOBRE_TARJETA = [
  "foreground",
  "card-foreground",
  "muted-foreground",
  "primary",
  "success",
  "warning",
  "info",
  "urgency-critical",
  "urgency-high",
  "urgency-medium",
  "urgency-low",
  "score-hot",
  "score-warm",
  "score-cold",
  "score-skip",
] as const;

/** Pares texto/superficie que no son la tarjeta pero sí existen en la UI. */
const PARES_PROPIOS = [
  ["popover-foreground", "popover"],
  ["secondary-foreground", "secondary"],
  ["accent-foreground", "accent"],
] as const;

/**
 * La rampa cálida del tema claro se comprueba además contra el fondo de
 * página, que es `40 22% 96%` y no blanco puro: es ~0,4 puntos de ratio más
 * exigente que la tarjeta, y es el margen que justifica que estos tokens estén
 * 1-3 puntos de luminosidad por debajo del mínimo teórico.
 */
const RAMPA_CLARA_SOBRE_FONDO = [
  "success",
  "warning",
  "info",
  "urgency-high",
  "urgency-medium",
  "urgency-low",
  "score-warm",
] as const;

/**
 * Deudas conocidas, ajenas a esta corrección (que es del tema claro). Se fija
 * el ratio actual como suelo en vez de excluirlas: no cumplen AA, pero al
 * menos no pueden empeorar sin que el test lo diga.
 *
 * - `oscuro/destructive` sobre `--card`: 4,21:1. Tocarlo significa mover el
 *   rojo del tema oscuro, que está fuera del alcance de este cambio.
 */
const DEUDAS: readonly (readonly [Tema, string, string, number])[] = [["oscuro", "destructive", "card", 4.2]];

describe("calculadora de contraste", () => {
  it("da 21:1 entre negro y blanco y 1:1 contra sí mismo", () => {
    const negro = hslToRgb(0, 0, 0);
    const blanco = hslToRgb(0, 0, 100);
    expect(ratioContraste(negro, blanco)).toBeCloseTo(21, 2);
    expect(ratioContraste(blanco, blanco)).toBeCloseTo(1, 5);
  });

  it("reproduce el gris de referencia de WCAG (#767676 sobre blanco = 4,54:1)", () => {
    // 46,7% de luminosidad neutra es exactamente #767676, el gris que la propia
    // norma usa como ejemplo del límite de AA sobre blanco.
    expect(ratioContraste(hslToRgb(0, 0, 46.27), hslToRgb(0, 0, 100))).toBeCloseTo(4.54, 1);
  });
});

describe("parseo de globals.css", () => {
  it("encuentra los dos temas con la paleta completa", () => {
    for (const tema of ["claro", "oscuro"] as const) {
      expect(TEMAS[tema].size).toBeGreaterThan(20);
      expect(TEMAS[tema].has("card")).toBe(true);
      expect(TEMAS[tema].has("warning")).toBe(true);
    }
  });

  it("descarta los tokens con alfa y los que no son color", () => {
    expect(TEMAS.claro.has("border")).toBe(false);
    expect(TEMAS.claro.has("radius")).toBe(false);
  });

  it("no confunde `.dark` con `:root`", () => {
    expect(TEMAS.claro.get("card")).not.toEqual(TEMAS.oscuro.get("card"));
  });
});

describe.each(["claro", "oscuro"] as const)("tema %s", (tema) => {
  it.each(TEXTO_SOBRE_TARJETA)("--%s pasa 4,5:1 como texto sobre la tarjeta", (token) => {
    const medido = ratio(tema, token, "card");
    expect(medido, `--${token} da ${medido.toFixed(2)}:1 sobre --card (mínimo ${AA_TEXTO})`).toBeGreaterThanOrEqual(
      AA_TEXTO,
    );
  });

  it.each(PARES_PROPIOS)("--%s pasa 4,5:1 sobre --%s", (token, superficie) => {
    const medido = ratio(tema, token, superficie);
    expect(
      medido,
      `--${token} da ${medido.toFixed(2)}:1 sobre --${superficie} (mínimo ${AA_TEXTO})`,
    ).toBeGreaterThanOrEqual(AA_TEXTO);
  });

  it("todos los --chart-* pasan 3:1 sobre la tarjeta", () => {
    const flojos = [...TEMAS[tema].keys()]
      .filter((token) => /^chart-\d+$/.test(token))
      .map((token) => ({ token, medido: ratio(tema, token, "card") }))
      .filter(({ medido }) => medido < AA_GRAFICO)
      .map(({ token, medido }) => `--${token}: ${medido.toFixed(2)}:1`);
    expect(flojos, `series por debajo de ${AA_GRAFICO}:1 sobre --card`).toEqual([]);
  });

  it("la paleta de series no está vacía", () => {
    expect([...TEMAS[tema].keys()].filter((t) => /^chart-\d+$/.test(t)).length).toBeGreaterThanOrEqual(10);
  });
});

describe("tema claro sobre el fondo de página", () => {
  it.each(RAMPA_CLARA_SOBRE_FONDO)("--%s aguanta 4,5:1 también sobre --background", (token) => {
    const medido = ratio("claro", token, "background");
    expect(
      medido,
      `--${token} da ${medido.toFixed(2)}:1 sobre --background (mínimo ${AA_TEXTO})`,
    ).toBeGreaterThanOrEqual(AA_TEXTO);
  });

  it("--chart-3 llega al 3:1 de objeto gráfico también sobre el fondo de página", () => {
    const medido = ratio("claro", "chart-3", "background");
    expect(medido, `--chart-3 da ${medido.toFixed(2)}:1 sobre --background`).toBeGreaterThanOrEqual(AA_GRAFICO);
  });
});

describe("deudas de contraste conocidas", () => {
  it.each(DEUDAS)("%s/--%s sobre --%s no empeora de %s:1", (tema, token, superficie, suelo) => {
    const medido = ratio(tema, token, superficie);
    expect(medido, `--${token} bajó a ${medido.toFixed(2)}:1 en el tema ${tema}`).toBeGreaterThanOrEqual(suelo);
  });
});
