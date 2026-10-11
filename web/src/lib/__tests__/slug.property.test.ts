import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { CCAA_SIN_ASIGNAR, esSlugOrgano, rutaHubCcaa, rutaHubCpv, rutaLicitacion, slugCcaa, slugificar } from "../slug";
import { comprobar, textoUnicode } from "@/test/propiedades";

/**
 * Un slug acaba en una URL pública que Google indexa, y sale de títulos que
 * escribe un órgano de contratación: comillas tipográficas, barras, símbolos,
 * mil caracteres. `slug.test.ts` fija los casos conocidos; aquí se dice que
 * **cualquier** título da una URL bien formada, que es lo que impide una ficha
 * inalcanzable (`/licitaciones//…`) o dos URLs para la misma página.
 */

/** Un título como los que llegan: texto libre con los separadores que rompen una ruta. */
const TITULO = fc.oneof(
  textoUnicode({ maxLength: 120 }),
  fc
    .array(
      fc.constantFrom(
        "Suministro",
        "contratación",
        "ÁREA",
        "nº",
        "2026",
        "/",
        "//",
        "-",
        "--",
        " ",
        "?",
        "#",
        "%2F",
        "«",
        "»",
        ".",
        "ñ",
      ),
      { maxLength: 40 },
    )
    .map((trozos) => trozos.join("")),
);
/** La referencia opaca del expediente: base64url, que incluye `-` y `_`. */
const REF = fc.stringMatching(/^[A-Za-z0-9_-]{6,22}$/);
const CCAA = fc.option(fc.oneof(TITULO, fc.constantFrom("Madrid", "Castilla-La Mancha", "Illes Balears", "")), {
  nil: null,
});

/** Minúsculas, dígitos y guiones simples, sin guion en los extremos; o nada. */
const SLUG_O_VACIO = /^(?:[a-z0-9]+(?:-[a-z0-9]+)*)?$/;

describe("slugificar · con cualquier texto", () => {
  it("da un slug bien formado de 80 caracteres como mucho", () => {
    comprobar(
      fc.property(TITULO, (titulo) => {
        const slug = slugificar(titulo);

        expect(slug).toMatch(SLUG_O_VACIO);
        expect(slug.length).toBeLessThanOrEqual(80);
        // La misma forma que exige la ruta de un órgano.
        if (slug) expect(esSlugOrgano(slug)).toBe(true);
      }),
    );
  });

  it("slugificar un slug no lo cambia", () => {
    // Si no fuese un punto fijo, una URL canónica redirigiría a otra distinta.
    comprobar(
      fc.property(TITULO, (titulo) => {
        const slug = slugificar(titulo);
        expect(slugificar(slug)).toBe(slug);
      }),
    );
  });

  it("no depende de mayúsculas ni de cómo venga codificado el acento", () => {
    comprobar(
      fc.property(fc.stringMatching(/^[a-zñáéíóúüA-ZÑÁÉÍÓÚÜ0-9 ./-]{0,60}$/), (titulo) => {
        const slug = slugificar(titulo);

        expect(slugificar(titulo.toUpperCase())).toBe(slug);
        expect(slugificar(titulo.normalize("NFD"))).toBe(slug);
      }),
    );
  });
});

describe("rutas públicas · con cualquier dato", () => {
  it("slugCcaa nunca queda vacío", () => {
    comprobar(
      fc.property(CCAA, (ccaa) => {
        const slug = slugCcaa(ccaa);

        expect(slug).not.toBe("");
        expect(esSlugOrgano(slug)).toBe(true);
        if (!slugificar(ccaa ?? "")) expect(slug).toBe(CCAA_SIN_ASIGNAR);
      }),
    );
  });

  it("la ficha tiene siempre cuatro segmentos, y el último es la referencia intacta", () => {
    comprobar(
      fc.property(CCAA, TITULO, REF, (ccaa, titulo, ref) => {
        const ruta = rutaLicitacion({ ccaa, titulo, ref });
        const segmentos = ruta.split("/");

        // "" · licitaciones · ccaa · slug · ref — ninguno vacío, ninguno de más.
        expect(segmentos).toHaveLength(5);
        expect(segmentos.slice(1).every(Boolean)).toBe(true);
        expect(segmentos[1]).toBe("licitaciones");
        expect(segmentos[4]).toBe(ref);
        // La ficha cuelga del hub de su comunidad.
        expect(ruta.startsWith(`${rutaHubCcaa(ccaa)}/`)).toBe(true);
        // Nada que haya que codificar: la URL que se enlaza es la que se sirve.
        expect(encodeURI(ruta)).toBe(ruta);
      }),
    );
  });

  it("el hub de un CPV sólo lleva dígitos, ocho como mucho", () => {
    comprobar(
      fc.property(fc.oneof(fc.stringMatching(/^\d{2,8}(-\d)?$/), textoUnicode({ maxLength: 20 })), (cpv) => {
        expect(rutaHubCpv(cpv)).toMatch(/^\/cpv\/\d{0,8}$/);
      }),
    );
  });
});
