import { describe, expect, it } from "vitest";
import {
  PREFIJO_PAGINACION_INTERNA,
  destinoPaginaInterna,
  esRutaPaginacionInterna,
  paginaDeQuery,
  paginaDeSegmento,
  rutaPublicaDePagina,
} from "@/lib/paginacion-hubs";

/**
 * La paginación de los hubs cambió de mecanismo —de leer `searchParams` en la
 * página a un rewrite del proxy— sin poder cambiar de comportamiento: la URL
 * `?p=N` está indexada, la enlaza la paginación y la declara el canonical.
 * Estos tests fijan las dos mitades de ese contrato: qué página sale de cada
 * `p` (idéntico a antes) y a dónde se reescribe.
 */

/** La regla que tenían las tres páginas cuando leían la query, copiada tal cual. */
function paginaDeAntes(query: { p?: string | string[] }): number {
  const n = Number(query.p);
  return Number.isInteger(n) && n > 1 ? n : 1;
}

/** Lo que Next entregaba en `searchParams.p` para una query dada. */
function comoLoEntregabaNext(params: URLSearchParams): { p?: string | string[] } {
  const valores = params.getAll("p");
  if (valores.length === 0) return {};
  return { p: valores.length === 1 ? valores[0] : valores };
}

function query(texto: string): URLSearchParams {
  return new URLSearchParams(texto);
}

describe("paginaDeQuery replica la regla de antes", () => {
  // Incluye las rarezas de `Number()` a propósito: son el comportamiento que
  // había en producción, y el objetivo es no cambiar ninguna URL.
  it.each([
    "",
    "p=2",
    "p=3",
    "p=1",
    "p=0",
    "p=-4",
    "p=abc",
    "p=2.5",
    "p=3.0",
    "p=03",
    "p=+5",
    "p=%203%20",
    "p=",
    "p",
    "p=1e1",
    "p=0x10",
    "p=Infinity",
    "p=1e400",
    "p=3&p=4",
    "p=3&p=3",
    "q=7",
    "p=9007199254740993",
  ])("?%s", (texto) => {
    const params = query(texto);
    expect(paginaDeQuery(params.getAll("p"))).toBe(paginaDeAntes(comoLoEntregabaNext(params)));
  });
});

describe("paginaDeSegmento", () => {
  it.each([
    ["2", 2],
    ["37", 37],
    ["9007199254740991", 9007199254740991],
  ])("%s es la página %d", (segmento, pagina) => {
    expect(paginaDeSegmento(segmento)).toBe(pagina);
  });

  it.each(["1", "0", "-2", "02", "2.5", "abc", "", " 2", "1e+21", "9007199254740993"])(
    "%j no lo escribe nunca el proxy: null (404 en la página)",
    (segmento) => {
      expect(paginaDeSegmento(segmento)).toBeNull();
    },
  );
});

describe("rutaPublicaDePagina", () => {
  it("la página 1 va sin query y el resto con ?p=", () => {
    expect(rutaPublicaDePagina("/cpv/72", 1)).toBe("/cpv/72");
    expect(rutaPublicaDePagina("/cpv/72", 4)).toBe("/cpv/72?p=4");
  });

  it("es la inversa de lo que lee el proxy", () => {
    // El canonical y la paginación emiten esta forma; si el proxy dejara de
    // entenderla, la URL indexada serviría la página 1.
    for (const pagina of [2, 3, 50]) {
      const url = new URL(rutaPublicaDePagina("/licitaciones/madrid", pagina), "https://tenderflow.es");
      expect(destinoPaginaInterna(url.pathname, url.searchParams)).toBe(
        `${PREFIJO_PAGINACION_INTERNA}/licitaciones/madrid/${pagina}`,
      );
    }
  });
});

describe("destinoPaginaInterna", () => {
  it.each([
    ["/licitaciones/madrid", "/hub-paginado/licitaciones/madrid/3"],
    ["/licitaciones/sin-comunidad", "/hub-paginado/licitaciones/sin-comunidad/3"],
    ["/licitaciones/organo/consejeria-de-sanidad", "/hub-paginado/licitaciones/organo/consejeria-de-sanidad/3"],
    ["/cpv/72000000", "/hub-paginado/cpv/72000000/3"],
  ])("el hub %s con ?p=3 va a %s", (ruta, interna) => {
    expect(destinoPaginaInterna(ruta, query("p=3"))).toBe(interna);
  });

  it.each(["", "p=1", "p=abc", "p=0", "p=3&p=4"])("un hub con ?%s es la página 1: sin rewrite", (texto) => {
    expect(destinoPaginaInterna("/licitaciones/madrid", query(texto))).toBeNull();
  });

  it.each([
    "/licitaciones",
    "/licitaciones/organo",
    "/licitaciones/%6Frgano",
    "/cpv",
    "/licitaciones/madrid/obras/EXP-1",
    "/aviso-legal",
    "/",
    "/resumen",
  ])("%s no es un hub que pagine", (ruta) => {
    // `/licitaciones/organo` es el índice de órganos, hermano estático de
    // `[ccaa]`: reescribirlo lo convertiría en el hub de la comunidad «organo».
    expect(destinoPaginaInterna(ruta, query("p=2"))).toBeNull();
  });

  it("conserva la codificación del hub para que Next decodifique igual que en la página 1", () => {
    expect(destinoPaginaInterna("/licitaciones/catalu%C3%B1a", query("p=2"))).toBe(
      "/hub-paginado/licitaciones/catalu%C3%B1a/2",
    );
  });
});

describe("esRutaPaginacionInterna", () => {
  it.each([
    "/hub-paginado",
    "/hub-paginado/licitaciones/madrid/2",
    "/hub-paginado/cpv/72/2",
    // Next casa las rutas también por su forma decodificada: la grafía
    // codificada del prefijo llegaría a la página interna igual.
    "/hub%2Dpaginado/licitaciones/madrid/2",
    "/%68ub-paginado/cpv/72/2",
    "/HUB-PAGINADO/cpv/72/2",
  ])("%s es interna", (ruta) => {
    expect(esRutaPaginacionInterna(ruta)).toBe(true);
  });

  it.each(["/", "/hub-paginadox", "/licitaciones/hub-paginado", "/hub", "/licitaciones/madrid"])(
    "%s no lo es",
    (ruta) => {
      expect(esRutaPaginacionInterna(ruta)).toBe(false);
    },
  );

  it("una secuencia % inválida no la saca del prefijo", () => {
    expect(esRutaPaginacionInterna("/hub-paginado/licitaciones/%E0%A4%A/2")).toBe(true);
  });
});
