/**
 * Tamaño de letra de `Input`: el que trae el llamador vale en todos los anchos.
 *
 * El primitivo llevaba `text-base md:text-sm`. tailwind-merge solo ve en
 * conflicto dos tamaños con la misma variante, así que un `text-xs` del
 * llamador quitaba `text-base` pero dejaba `md:text-sm`; y en la hoja las
 * utilidades con `md:` van detrás de las que no llevan variante, de modo que
 * desde 768 px ganaba `md:text-sm`: el buscador del tablero pedía 12 px y salía
 * a 14. jsdom no aplica la hoja, así que se comprueba lo que la decide: qué
 * tamaños quedan en la lista final de clases.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { Input } from "@/components/ui/input";

/** Clases de tamaño o color del texto del propio campo (no del placeholder ni del botón de fichero). */
function clasesDeTexto(campo: HTMLElement): string[] {
  return [...campo.classList].filter((c) => /^([\w-]+:)*text-/.test(c) && !/^(placeholder|file):/.test(c));
}

describe("Input — tamaño de letra", () => {
  it("sin tamaño propio usa el de campo", () => {
    render(<Input aria-label="campo" />);
    expect(clasesDeTexto(screen.getByRole("textbox"))).toEqual(["text-campo"]);
  });

  it.each(["text-tf-meta", "text-xs", "text-[12px]"])("con %s, es el único tamaño que queda", (tamano) => {
    render(<Input aria-label="campo" className={`h-7 pl-8 ${tamano}`} />);
    expect(clasesDeTexto(screen.getByRole("textbox"))).toEqual([tamano]);
  });

  it("un tamaño solo desde md conserva el de campo por debajo", () => {
    render(<Input aria-label="campo" className="md:text-xs" />);
    expect(clasesDeTexto(screen.getByRole("textbox"))).toEqual(["text-campo", "md:text-xs"]);
  });

  it("un color del llamador no se lleva el tamaño", () => {
    render(<Input aria-label="campo" className="text-muted-foreground" />);
    expect(clasesDeTexto(screen.getByRole("textbox"))).toEqual(["text-campo", "text-muted-foreground"]);
  });

  it("el tamaño de campo es de 16 px fuera de md y de 14 desde md", () => {
    // Los 16 px no son estética: iOS amplía la página al enfocar un campo más pequeño.
    const css = readFileSync(
      path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../app/globals.css"),
      "utf8",
    );
    expect(css).toMatch(/@theme\s*\{\s*--text-campo:\s*var\(--text-base\);/);
    expect(css).toMatch(/@variant md\s*\{\s*--text-campo:\s*var\(--text-sm\);/);
  });
});
