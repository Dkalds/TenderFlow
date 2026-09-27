/**
 * Layout raíz: la tipografía de la aplicación.
 *
 * Fija la decisión del 2026-09-26 sobre titulares: Fraunces es la
 * `--font-display` de toda la aplicación, se declara una sola vez
 * (`lib/tipografia.ts`) con su eje óptico, y el layout raíz pone las variables de
 * las tres familias en `<html>`. Space Grotesk salió; si vuelve a entrar por
 * costumbre, o si la superficie pública vuelve a cargar su propia copia de
 * Fraunces (dos descargas, dos nombres de familia), esto lo dice.
 *
 * `next/font` solo funciona dentro del compilador de Next, así que aquí se
 * sustituye por un cargador que apunta con qué opciones se le llamó.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import RootLayout from "../layout";

type Llamada = { familia: string; opciones: Record<string, unknown> };

const llamadas = vi.hoisted((): Llamada[] => []);

vi.mock("next/font/google", () => {
  const cargador = (familia: string) => (opciones: Record<string, unknown>) => {
    llamadas.push({ familia, opciones });
    return { className: `fuente-${familia}`, variable: `variable-${familia}`, style: { fontFamily: familia } };
  };
  return { Geist: cargador("Geist"), Geist_Mono: cargador("Geist_Mono"), Fraunces: cargador("Fraunces") };
});
vi.mock("@vercel/speed-insights/next", () => ({ SpeedInsights: () => null }));
vi.mock("@vercel/analytics/next", () => ({ Analytics: () => null }));
vi.mock("@/components/client-error-listener", () => ({ ClientErrorListener: () => null }));

function opcionesDe(familia: string): Record<string, unknown> {
  const llamada = llamadas.find((l) => l.familia === familia);
  if (!llamada) throw new Error(`No se declaró ${familia}`);
  return llamada.opciones;
}

describe("tipografía de la aplicación", () => {
  it("declara cada familia una sola vez: sans, mono y la de titulares", () => {
    expect(llamadas.map((l) => l.familia).sort()).toEqual(["Fraunces", "Geist", "Geist_Mono"]);
  });

  it("los titulares son Fraunces con eje óptico, en `--font-display`", () => {
    const fraunces = opcionesDe("Fraunces");
    expect(fraunces.variable).toBe("--font-display");
    expect(fraunces.axes).toEqual(["opsz"]);
    expect(fraunces.subsets).toEqual(["latin"]);
  });

  it("la sans y la mono conservan las variables que lee globals.css", () => {
    expect(opcionesDe("Geist").variable).toBe("--font-geist-sans");
    expect(opcionesDe("Geist_Mono").variable).toBe("--font-geist-mono");
    // La mono no es primer render crítico: no compite con el preload del h1.
    expect(opcionesDe("Geist_Mono").preload).toBe(false);
  });

  it("pone las tres variables en <html>, para toda la aplicación", () => {
    const html = renderToStaticMarkup(
      <RootLayout>
        <p>contenido</p>
      </RootLayout>,
    );
    const clase = /<html[^>]*\sclass="([^"]*)"/.exec(html)?.[1] ?? "";
    expect(clase.split(" ").sort()).toEqual(["variable-Fraunces", "variable-Geist", "variable-Geist_Mono"]);
    expect(html).toContain('lang="es"');
  });

  it("la superficie pública no declara su propia fuente de titulares", () => {
    const fuente = readFileSync(
      path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../(publico)/layout.tsx"),
      "utf8",
    );
    expect(fuente).not.toMatch(/from\s+["']next\/font/);
  });
});
