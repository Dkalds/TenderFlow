import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { safeRedirectPath } from "../safe-redirect";
import { comprobar, textoUnicode } from "@/test/propiedades";

/**
 * `?redirect=` lo escribe quien manda el enlace, y lo que sale de aquí acaba en
 * `window.location.href` nada más entrar. La promesa del módulo no es «rechaza
 * estas cinco formas» sino «con cualquier texto, el destino sigue siendo esta
 * aplicación», y eso sólo se puede decir como propiedad.
 *
 * Los ejemplos de `safe-redirect.test.ts` no la cubrían: la primera versión de
 * este fichero encontró `/.//evil.example`, que pasaba todos los filtros —no
 * empieza por `//`— y salía convertido en `//evil.example` por la
 * normalización de la URL. Un navegador lee eso como otro host.
 */

/** Los orígenes desde los que el navegador resolvería el destino. */
const ORIGENES = ["https://tenderflow.example", "http://localhost:3000"] as const;

/**
 * Trozos con los que se fabrica un redirect hostil: separadores repetidos,
 * segmentos de punto (crudos y codificados), los caracteres que el parser de
 * URLs descarta en silencio (tabulador y saltos de línea) y los que cambian de
 * componente (`?`, `#`, `@`, `:`).
 */
const TROZO_HOSTIL = fc.constantFrom(
  "/",
  "//",
  ".",
  "..",
  "%2e",
  "%2E",
  "%2f",
  "%5c",
  "\\",
  "\t",
  "\n",
  "\r",
  " ",
  "@",
  ":",
  "?",
  "#",
  ";",
  "&",
  "=",
  "%00",
  "\0",
  "evil.example",
  "https:",
  "javascript:",
  "resumen",
  "a",
);

const CANDIDATA = fc.oneof(
  fc.array(TROZO_HOSTIL, { maxLength: 10 }).map((trozos) => trozos.join("")),
  // La mayoría de los textos al azar no empiezan por `/` y mueren en el primer
  // filtro; con la barra delante llegan al parser, que es donde está el riesgo.
  fc.array(TROZO_HOSTIL, { maxLength: 10 }).map((trozos) => `/${trozos.join("")}`),
  textoUnicode({ maxLength: 40 }),
  textoUnicode({ maxLength: 40 }).map((texto) => `/${texto}`),
);

describe("safeRedirectPath · con cualquier texto", () => {
  it("el destino nunca sale de la aplicación", () => {
    comprobar(
      fc.property(CANDIDATA, fc.constantFrom(...ORIGENES), (candidata, origen) => {
        const destino = safeRedirectPath(candidata);

        expect(destino.startsWith("/")).toBe(true);
        expect(destino.startsWith("//")).toBe(false);
        expect(destino).not.toContain("\\");
        // Lo que de verdad importa: resuelto como lo resuelve el navegador,
        // sigue en el mismo origen.
        expect(new URL(destino, origen).origin).toBe(origen);
      }),
      { numRuns: 1000 },
    );
  });

  it("sanear dos veces es lo mismo que sanear una", () => {
    comprobar(
      fc.property(CANDIDATA, (candidata) => {
        const destino = safeRedirectPath(candidata);
        expect(safeRedirectPath(destino)).toBe(destino);
      }),
      { numRuns: 1000 },
    );
  });

  it("una ruta interna corriente pasa sin que le cambie nada", () => {
    const segmento = fc.stringMatching(/^[a-z0-9][a-z0-9-]{0,11}$/);
    const par = fc.tuple(fc.stringMatching(/^[a-z_]{1,10}$/), fc.stringMatching(/^[A-Za-z0-9-]{0,10}$/));
    comprobar(
      fc.property(
        fc.array(segmento, { minLength: 1, maxLength: 4 }),
        fc.array(par, { maxLength: 3 }),
        fc.option(segmento, { nil: null }),
        (segmentos, pares, ancla) => {
          const query = pares.map(([clave, valor]) => `${clave}=${valor}`).join("&");
          const ruta = `/${segmentos.join("/")}${query ? `?${query}` : ""}${ancla ? `#${ancla}` : ""}`;
          expect(safeRedirectPath(ruta)).toBe(ruta);
        },
      ),
    );
  });
});

describe("safeRedirectPath · contraejemplos que encontró la propiedad", () => {
  // Se quedan con nombre: si alguien reescribe el saneado, estos son los casos
  // que un filtro sobre el texto de entrada no ve.
  it.each([
    ["segmento de punto delante de la doble barra", "/.//evil.example"],
    ["subir un nivel deja la doble barra al principio", "/a/..//evil.example"],
    ["el punto codificado se normaliza igual que el crudo", "/%2e//evil.example"],
    ["el tabulador desaparece al parsear", "/.\t//evil.example"],
    ["con ruta, query y ancla detrás", "/.//evil.example/entrar?x=1#y"],
  ])("%s", (_caso, candidata) => {
    expect(safeRedirectPath(candidata)).toBe("/resumen");
  });
});
