import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  PREFIJO_PAGINACION_INTERNA,
  destinoPaginaInterna,
  esRutaPaginacionInterna,
  paginaDeQuery,
  paginaDeSegmento,
  rutaPublicaDePagina,
} from "@/lib/paginacion-hubs";
import { comprobar, textoUnicode } from "@/test/propiedades";

/**
 * La paginación de los hubs tiene tres piezas que tienen que entenderse: la URL
 * pública que se enlaza (`?p=N`), el rewrite del proxy a un segmento interno y
 * la página interna que lee ese segmento. `paginacion-hubs.test.ts` fija cada
 * pieza con ejemplos; aquí se comprueba el circuito entero con cualquier hub y
 * cualquier número de página, que es donde un cambio en una pieza rompe otra.
 */

const SLUG = fc.stringMatching(/^[a-z0-9]+(-[a-z0-9]+){0,3}$/);
/** Las tres familias de hub que paginan. `organo` a secas es el índice, no un hub. */
const HUB = fc.oneof(
  SLUG.filter((slug) => slug !== "organo").map((slug) => `/licitaciones/${slug}`),
  SLUG.map((slug) => `/licitaciones/organo/${slug}`),
  fc.stringMatching(/^\d{2,8}$/).map((cpv) => `/cpv/${cpv}`),
);
const PAGINA = fc.integer({ min: 2, max: Number.MAX_SAFE_INTEGER });

/** Parte una URL relativa en lo que recibe el proxy: pathname y query. */
function comoLaRecibeElProxy(url: string): [string, URLSearchParams] {
  const [pathname, query = ""] = url.split("?");
  return [pathname, new URLSearchParams(query)];
}

describe("paginación de hubs · el circuito entero", () => {
  it("la página que se enlaza es la que acaba leyendo la página interna", () => {
    comprobar(
      fc.property(HUB, PAGINA, (hub, pagina) => {
        const publica = rutaPublicaDePagina(hub, pagina);
        const destino = destinoPaginaInterna(...comoLaRecibeElProxy(publica));

        expect(destino).toBe(`${PREFIJO_PAGINACION_INTERNA}${hub}/${pagina}`);
        expect(paginaDeSegmento(destino!.split("/").at(-1)!)).toBe(pagina);
        // Lo que el proxy escribe es justo lo que bloquea si llega de fuera.
        expect(esRutaPaginacionInterna(destino!)).toBe(true);
      }),
    );
  });

  it("la página 1 (o menos) no lleva query ni se reescribe", () => {
    comprobar(
      fc.property(HUB, fc.integer({ min: -1000, max: 1 }), (hub, pagina) => {
        const publica = rutaPublicaDePagina(hub, pagina);

        expect(publica).toBe(hub);
        expect(destinoPaginaInterna(...comoLaRecibeElProxy(publica))).toBeNull();
      }),
    );
  });

  it("un hub nunca se confunde con el árbol interno, ni al revés", () => {
    comprobar(
      fc.property(HUB, PAGINA, (hub, pagina) => {
        expect(esRutaPaginacionInterna(hub)).toBe(false);
        // Una ruta interna pedida con `?p=` no se vuelve a reescribir.
        const interna = `${PREFIJO_PAGINACION_INTERNA}${hub}/${pagina}`;
        expect(destinoPaginaInterna(interna, new URLSearchParams({ p: String(pagina) }))).toBeNull();
      }),
    );
  });
});

describe("paginaDeQuery · con cualquier valor de `p`", () => {
  /** Lo que alguien puede escribir en la barra de direcciones. */
  const VALOR_DE_P = fc.oneof(
    textoUnicode({ maxLength: 10 }),
    fc.integer().map(String),
    fc.double().map(String),
    fc.constantFrom("", "1", "2", "02", "+3", " 4 ", "5.0", "1e3", "1e21", "0x10", "9007199254740993", "Infinity"),
  );

  it("siempre da un entero mayor o igual que 1", () => {
    comprobar(
      fc.property(VALOR_DE_P, (valor) => {
        const pagina = paginaDeQuery([valor]);

        expect(Number.isInteger(pagina)).toBe(true);
        expect(pagina).toBeGreaterThanOrEqual(1);
      }),
    );
  });

  it("con la clave ausente o repetida es la página 1", () => {
    comprobar(
      fc.property(fc.array(VALOR_DE_P, { maxLength: 4 }), (valores) => {
        fc.pre(valores.length !== 1);
        expect(paginaDeQuery(valores)).toBe(1);
      }),
    );
  });

  it("lo que el proxy escribe, la página interna lo lee igual o lo rechaza: nunca otra página", () => {
    // El fallo que esto impide: pedir `?p=X`, que el rewrite escriba un
    // segmento y que la página interna sirva una página distinta de la pedida.
    comprobar(
      fc.property(VALOR_DE_P, (valor) => {
        const pedida = paginaDeQuery([valor]);
        const leida = paginaDeSegmento(String(pedida));

        if (pedida === 1) {
          // La 1 nunca llega al árbol interno, y si llegara sería un 404.
          expect(leida).toBeNull();
        } else if (Number.isSafeInteger(pedida)) {
          expect(leida).toBe(pedida);
        } else {
          expect(leida).toBeNull();
        }
      }),
    );
  });
});

describe("paginaDeSegmento · con cualquier segmento", () => {
  it("cada página tiene una sola grafía: la que acepta es la que escribiría", () => {
    // `02`, `2.0` o `+2` servirían la página 2 bajo otra URL: contenido
    // duplicado dentro del árbol que el proxy promete que tiene una entrada
    // por página.
    comprobar(
      fc.property(
        fc.oneof(
          textoUnicode({ maxLength: 10 }),
          fc.integer().map(String),
          fc.constantFrom("2", "02", "2.0", "+2", " 2", "2 ", "1e3", "٢", "2\n"),
        ),
        (segmento) => {
          const pagina = paginaDeSegmento(segmento);

          if (pagina !== null) {
            expect(String(pagina)).toBe(segmento);
            expect(pagina).toBeGreaterThan(1);
            expect(Number.isSafeInteger(pagina)).toBe(true);
          }
        },
      ),
    );
  });
});

describe("esRutaPaginacionInterna · todas las grafías que el router acepta", () => {
  /** Reescribe cada carácter como está, en mayúscula o codificado con `%`. */
  const disfrazada = (ruta: string) =>
    fc
      .array(fc.constantFrom("igual", "mayuscula", "codificado", "codificado-minuscula"), {
        minLength: ruta.length,
        maxLength: ruta.length,
      })
      .map((formas) =>
        [...ruta]
          .map((letra, indice) => {
            // La barra no se disfraza: `%2F` no separa segmentos para el router.
            if (letra === "/") return letra;
            const hex = letra.charCodeAt(0).toString(16).padStart(2, "0");
            switch (formas[indice]) {
              case "mayuscula":
                return letra.toUpperCase();
              case "codificado":
                return `%${hex.toUpperCase()}`;
              case "codificado-minuscula":
                return `%${hex}`;
              default:
                return letra;
            }
          })
          .join(""),
      );

  it("el prefijo se reconoce aunque venga en mayúsculas o codificado", () => {
    // Es una lista de denegación: sólo vale si cubre todas las formas de
    // escribir la misma ruta.
    comprobar(
      fc.property(
        fc.tuple(HUB, PAGINA).chain(([hub, pagina]) => disfrazada(`${PREFIJO_PAGINACION_INTERNA}${hub}/${pagina}`)),
        (ruta) => {
          expect(esRutaPaginacionInterna(ruta)).toBe(true);
        },
      ),
    );
  });

  it("una ruta con una secuencia `%` rota no lanza", () => {
    comprobar(
      fc.property(textoUnicode({ maxLength: 20 }), (resto) => {
        const ruta = `/licitaciones/%E0%A4%A${resto}`;

        expect(() => esRutaPaginacionInterna(ruta)).not.toThrow();
        expect(() => destinoPaginaInterna(ruta, new URLSearchParams("p=2"))).not.toThrow();
      }),
    );
  });
});

describe("destinoPaginaInterna · sólo un hub exacto se reescribe", () => {
  // Los dos tests de abajo salen del informe de mutación (Stryker, 2026-10-11):
  // a las tres expresiones de `HUBS_PAGINADOS` se les podía quitar el `^` o el
  // `$` sin que fallara nada. Sin anclas, el proxy reescribiría a una página
  // interna inexistente cualquier ruta que *contuviera* un hub.
  it("ni con algo delante ni con un segmento detrás", () => {
    comprobar(
      fc.property(HUB, SLUG, PAGINA, (hub, extra, pagina) => {
        const query = new URLSearchParams({ p: String(pagina) });

        expect(destinoPaginaInterna(`/${extra}${hub}`, query)).toBeNull();
        expect(destinoPaginaInterna(`${hub}/${extra}`, query)).toBeNull();
      }),
    );
  });

  it("una comunidad cuyo slug empieza por «organo» sigue siendo un hub", () => {
    // La exclusión es del índice de órganos (`/licitaciones/organo`), no de
    // todo lo que empiece igual.
    comprobar(
      fc.property(SLUG, PAGINA, (resto, pagina) => {
        const hub = `/licitaciones/organo${resto}`;
        const query = new URLSearchParams({ p: String(pagina) });

        expect(destinoPaginaInterna(hub, query)).toBe(`${PREFIJO_PAGINACION_INTERNA}${hub}/${pagina}`);
      }),
    );
  });
});
