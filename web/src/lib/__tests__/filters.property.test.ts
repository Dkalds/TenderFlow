import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { EMPTY_SCOPE, type ScopeSnapshot, appendFiltersToPath, mergeFiltersIntoPath, scopeKey } from "@/lib/filters";
import { comprobar, textoUnicode } from "@/test/propiedades";

/**
 * La parte pura de `lib/filters.ts`: cómo se compara un ámbito con otro
 * (`scopeKey`, de la que depende el historial de deshacer) y cómo viaja el
 * ámbito en los enlaces (`appendFiltersToPath` / `mergeFiltersIntoPath`).
 *
 * Los hooks no entran aquí: montar `useFilters` cuesta decenas de milisegundos
 * por caso y sus idas y vueltas ya están en `filters.test.ts`.
 */

const CLAVES_AMBITO = Object.keys(EMPTY_SCOPE) as (keyof ScopeSnapshot)[];

function instantanea(valor: fc.Arbitrary<string>): fc.Arbitrary<ScopeSnapshot> {
  return fc
    .dictionary(fc.constantFrom(...CLAVES_AMBITO), valor, { maxKeys: 4 })
    .map((parcial) => ({ ...EMPTY_SCOPE, ...parcial }));
}

describe("scopeKey", () => {
  it("dos ámbitos tienen la misma clave si y sólo si son el mismo ámbito", () => {
    // El historial decide por esta cadena si el ámbito cambió. Dos ámbitos
    // distintos con la misma clave serían un paso de «deshacer» que se pierde.
    // Valores sin `&`: con él la propiedad no se cumple (ver el caso de abajo).
    const valor = fc.oneof(
      fc.constantFrom("", "PUB", "PUB,ADJ", "true", "2026-01-01", "a=b"),
      textoUnicode({ maxLength: 8 }).filter((texto) => !texto.includes("&")),
    );
    const pareja = fc.oneof(
      fc.tuple(instantanea(valor), instantanea(valor)),
      // Dos copias del mismo ámbito: sin esto casi ninguna pareja sería igual
      // y la mitad «mismo ámbito ⇒ misma clave» no se probaría.
      instantanea(valor).map((ambito): [ScopeSnapshot, ScopeSnapshot] => [ambito, { ...ambito }]),
    );
    comprobar(
      fc.property(pareja, ([uno, otro]) => {
        const mismoAmbito = CLAVES_AMBITO.every((clave) => uno[clave] === otro[clave]);
        expect(scopeKey(uno) === scopeKey(otro)).toBe(mismoAmbito);
      }),
    );
  });

  /**
   * Contraejemplo de la propiedad de arriba cuando los valores pueden llevar
   * `&`: la clave une los pares con `&` sin escapar nada, así que un valor que
   * contenga `&<clave siguiente>=` se confunde con el parámetro siguiente.
   *
   * No es explotable ni fácil de provocar —hace falta que el texto buscado
   * contenga literalmente `&fecha_desde=` y pasar de un ámbito al otro en un
   * solo cambio—, pero `q` es texto libre y `&` es un carácter corriente en
   * él. El arreglo es de una línea (la serialización con `JSON.stringify` que
   * ya usa `useScopeSnapshot`), y cambia el formato de la clave: por eso se
   * deja señalado y no se toca.
   */
  it.fails("distingue dos ámbitos aunque un valor contenga el separador", () => {
    const uno: ScopeSnapshot = { ...EMPTY_SCOPE, q: "&fecha_desde=" };
    const otro: ScopeSnapshot = { ...EMPTY_SCOPE, fecha_desde: "&fecha_desde=" };

    expect(scopeKey(uno)).not.toBe(scopeKey(otro));
  });
});

/* ── El ámbito en los enlaces ─────────────────────────────────────────── */

const RUTA = fc
  .array(fc.stringMatching(/^[a-z][a-z-]{0,9}$/), { minLength: 1, maxLength: 3 })
  .map((segmentos) => `/${segmentos.join("/")}`);
const VALOR = textoUnicode({ minLength: 1, maxLength: 10 });
/** Pocas claves, y compartidas entre el enlace y el ámbito, para que choquen a menudo. */
const CLAVE = fc.constantFrom("vista", "lic", "estado", "ccaa", "fecha_desde", "solo_abiertas");

/** La query del ámbito tal como la entrega `useFiltersQueryString`: `?…`, sin claves repetidas, o "". */
const QUERY_DEL_AMBITO = fc.dictionary(CLAVE, VALOR, { maxKeys: 4 }).map((pares) => {
  const qs = new URLSearchParams(pares).toString();
  return qs ? `?${qs}` : "";
});
/** La query propia de un enlace: puede repetir clave, y entonces vale la última. */
const QUERY_DEL_ENLACE = fc.array(fc.tuple(CLAVE, VALOR), { maxLength: 4 });

function enlace(ruta: string, pares: [string, string][]): string {
  const propia = new URLSearchParams(pares).toString();
  return propia ? `${ruta}?${propia}` : ruta;
}

describe("mergeFiltersIntoPath", () => {
  it("lleva todo el ámbito, y en lo que choca gana el enlace", () => {
    comprobar(
      fc.property(RUTA, QUERY_DEL_ENLACE, QUERY_DEL_AMBITO, (ruta, pares, ambito) => {
        const destino = mergeFiltersIntoPath(enlace(ruta, pares), ambito);

        const [base, query = "", ...sobra] = destino.split("?");
        // La ruta no se toca y no aparece un segundo `?`.
        expect(base).toBe(ruta);
        expect(sobra).toEqual([]);

        const resultado = new URLSearchParams(query);
        const delEnlace = new Map(pares);
        const delAmbito = new URLSearchParams(ambito);
        const esperado = new Map([...delAmbito, ...delEnlace]);

        expect(new Map(resultado)).toEqual(esperado);
        // Al fusionar no queda ninguna clave duplicada: lo que el destino lee
        // con `get()` es todo lo que hay. Sin ámbito el enlace no se reescribe
        // (propiedad de más abajo), así que conserva lo que trajera.
        if (ambito) expect([...resultado.keys()]).toHaveLength(esperado.size);
      }),
    );
  });

  it("fusionar dos veces el mismo ámbito es lo mismo que fusionarlo una", () => {
    comprobar(
      fc.property(RUTA, QUERY_DEL_ENLACE, QUERY_DEL_AMBITO, (ruta, pares, ambito) => {
        const una = mergeFiltersIntoPath(enlace(ruta, pares), ambito);
        expect(mergeFiltersIntoPath(una, ambito)).toBe(una);
      }),
    );
  });

  it("sin ámbito activo devuelve el enlace tal cual", () => {
    comprobar(
      fc.property(RUTA, QUERY_DEL_ENLACE, (ruta, pares) => {
        const href = enlace(ruta, pares);
        expect(mergeFiltersIntoPath(href, "")).toBe(href);
      }),
    );
  });

  it("con el enlace limpio coincide con appendFiltersToPath", () => {
    // Las dos funciones sólo se distinguen cuando el enlace trae query propia;
    // si divergieran antes, el mismo destino tendría dos URLs según quién enlace.
    comprobar(
      fc.property(RUTA, QUERY_DEL_AMBITO, (ruta, ambito) => {
        expect(mergeFiltersIntoPath(ruta, ambito)).toBe(appendFiltersToPath(ruta, ambito));
      }),
    );
  });
});

describe("appendFiltersToPath", () => {
  it("un enlace con query propia nunca cambia, traiga lo que traiga el ámbito", () => {
    comprobar(
      fc.property(RUTA, QUERY_DEL_ENLACE, QUERY_DEL_AMBITO, (ruta, pares, ambito) => {
        fc.pre(pares.length > 0);
        const href = enlace(ruta, pares);
        expect(appendFiltersToPath(href, ambito)).toBe(href);
      }),
    );
  });
});
