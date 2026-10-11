import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  type FilterValues,
  type SearchParamsServidor,
  filterParamsFromSearch,
  filtersToParams,
} from "@/lib/filter-params";
import { comprobar, textoUnicode } from "@/test/propiedades";

/**
 * El ámbito viaja como query string: se escribe en la URL, se comparte, se
 * recarga y se vuelve a leer —en el navegador y, para el prefetch, en el
 * servidor—. `filter-params.test.tsx` fija la paridad con el hook sobre siete
 * URLs escritas a mano; aquí se dice lo mismo para cualquier ámbito: lo que se
 * escribe es lo que se lee, lo lea quien lo lea.
 */

/** Las claves que `filtersToParams` puede emitir. Una más sería un filtro que la API no conoce. */
const CLAVES_API = [
  "q",
  "fecha_desde",
  "fecha_hasta",
  "estado",
  "ccaa",
  "tecnologia",
  "importe_min",
  "solo_abiertas",
  "procedimiento",
  "provincia",
  "importe_max",
] as const;

/** Un valor de lista: no vacío y sin coma, que es el separador en la URL. */
const VALOR_DE_LISTA = textoUnicode({ minLength: 1, maxLength: 12 }).filter((texto) => !texto.includes(","));
const LISTA = fc.array(VALOR_DE_LISTA, { maxLength: 4 });
const FECHA = fc.option(
  fc
    .date({ min: new Date("2000-01-01"), max: new Date("2099-12-31"), noInvalidDate: true })
    .map((fecha) => fecha.toISOString().slice(0, 10)),
  { nil: null },
);
// Cualquier `number`, no sólo los importes razonables: -0, decimales, 1e21,
// infinitos y NaN también tienen que sobrevivir a String() → Number().
const IMPORTE = fc.option(fc.oneof(fc.nat(), fc.double()), { nil: null });

const AMBITO: fc.Arbitrary<FilterValues> = fc.record({
  q: textoUnicode({ maxLength: 30 }),
  rango: fc.record({ desde: FECHA, hasta: FECHA }),
  estados: LISTA,
  ccaas: LISTA,
  tecnologias: LISTA,
  importeMin: IMPORTE,
  soloAbiertas: fc.boolean(),
  procedimientos: LISTA,
  provincias: LISTA,
  importeMax: IMPORTE,
});

/** Una query cualquiera: claves del ámbito y ajenas, repetidas, vacías o con basura. */
const VALOR_CRUDO = fc.oneof(
  textoUnicode({ maxLength: 12 }),
  fc.constantFrom("", "true", "false", "0", "150000", "1e3", " 7 ", "abc", ",", "a,,b", "PUB,ADJ"),
);
const QUERY_CRUDA = fc.array(
  fc.tuple(fc.constantFrom(...CLAVES_API, "vista", "p"), fc.array(VALOR_CRUDO, { minLength: 1, maxLength: 3 })),
  { maxLength: 8 },
);

function comoUrl(pares: [string, string[]][]): URLSearchParams {
  const params = new URLSearchParams();
  for (const [clave, valores] of pares) for (const valor of valores) params.append(clave, valor);
  return params;
}

/** Lo que Next entrega en `searchParams` a una página de servidor para esa misma URL. */
function comoLoEntregaNext(params: URLSearchParams): SearchParamsServidor {
  const servidor: SearchParamsServidor = {};
  for (const clave of new Set(params.keys())) {
    const valores = params.getAll(clave);
    servidor[clave] = valores.length === 1 ? valores[0] : valores;
  }
  return servidor;
}

describe("filtersToParams ⇄ filterParamsFromSearch · ida y vuelta", () => {
  it("un ámbito escrito en la URL se vuelve a leer idéntico", () => {
    comprobar(
      fc.property(AMBITO, (ambito) => {
        const escrito = filtersToParams(ambito);
        // Por la barra de direcciones de verdad: serializado a texto y vuelto a parsear.
        const enLaBarra = new URLSearchParams(new URLSearchParams(escrito).toString());

        expect(filterParamsFromSearch(enLaBarra)).toEqual(escrito);
      }),
    );
  });

  it("sólo emite claves que la API conoce, y ninguna vacía", () => {
    comprobar(
      fc.property(AMBITO, (ambito) => {
        for (const [clave, valor] of Object.entries(filtersToParams(ambito))) {
          expect(CLAVES_API).toContain(clave);
          expect(valor).not.toBe("");
        }
      }),
    );
  });
});

describe("filterParamsFromSearch · con cualquier query", () => {
  it("el servidor y el navegador leen lo mismo de la misma URL", () => {
    // Es la condición del prefetch: si las dos lecturas divergen, la clave
    // hidratada no es la que pide el cliente y la consulta se paga dos veces.
    comprobar(
      fc.property(QUERY_CRUDA, (pares) => {
        const url = comoUrl(pares);
        expect(filterParamsFromSearch(comoLoEntregaNext(url))).toEqual(filterParamsFromSearch(url));
      }),
    );
  });

  it("releer lo ya leído no cambia nada", () => {
    // Si no fuese idempotente, navegar con el ámbito a cuestas lo iría
    // deformando un poco en cada salto.
    comprobar(
      fc.property(QUERY_CRUDA, (pares) => {
        const leido = filterParamsFromSearch(comoUrl(pares));
        expect(filterParamsFromSearch(leido)).toEqual(leido);
      }),
    );
  });

  it("nunca manda a la API una clave ajena ni un valor vacío", () => {
    comprobar(
      fc.property(QUERY_CRUDA, (pares) => {
        for (const [clave, valor] of Object.entries(filterParamsFromSearch(comoUrl(pares)))) {
          expect(CLAVES_API).toContain(clave);
          expect(valor).not.toBe("");
        }
      }),
    );
  });

  it("con la clave repetida gana el primer valor, como en nuqs", () => {
    comprobar(
      fc.property(VALOR_DE_LISTA, VALOR_DE_LISTA, (primero, segundo) => {
        const url = comoUrl([["ccaa", [primero, segundo]]]);
        expect(filterParamsFromSearch(url)).toEqual({ ccaa: primero });
      }),
    );
  });
});

describe("filterParamsFromSearch · contraejemplos pendientes de decisión", () => {
  /**
   * La propiedad «el importe que llega a la API es un número» falla con
   * cualquier texto que `Number()` no entienda. `?importe_min=abc` —una URL
   * retocada a mano o cortada al pegarla— manda `importe_min=NaN`, la API lo
   * rechaza con 422 (el parámetro es `float` con `ge=0`) y todos los paneles
   * de la pantalla quedan en error por un filtro que el usuario no ve en
   * ningún chip. `useFilters` hace la misma conversión, así que las dos
   * lecturas coinciden: el arreglo, si se decide, va en los dos sitios.
   *
   * `it.fails` y no un arreglo porque ignorar el filtro en silencio también es
   * una decisión de producto. Cuando se tome, este test pasa a `it`.
   */
  it.fails("un importe que no es un número no viaja a la API", () => {
    const leido = filterParamsFromSearch(new URLSearchParams("importe_min=abc&importe_max=1e999"));

    expect(leido).toEqual({});
  });
});
