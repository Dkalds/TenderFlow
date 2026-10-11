import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { DEFAULT_WEIGHTS, PENALIZACIONES, esPenalizacion, hydrateWeights, sumWeights } from "../_lib/pesos";
import { dimensionesLibres, repartirPesos, topeDePeso } from "../_lib/reparto-pesos";
import { comprobar } from "@/test/propiedades";

/**
 * `reparto-pesos.test.ts` recorre los 101 valores de cada dimensión sobre **un**
 * reparto de partida y sin fijar nada. La promesa del módulo es más ancha —con
 * cualquier reparto, cualquier dimensión, cualquier valor y cualquier conjunto
 * de fijadas, la suma sigue en 100— y eso es lo que se comprueba aquí.
 */

const DIMENSIONES = Object.keys(DEFAULT_WEIGHTS);
const PENALIZACION = Object.keys(PENALIZACIONES)[0];

/**
 * Un reparto válido: seis enteros no negativos que suman 100, más la
 * penalización. Sale de cinco cortes en [0, 100]: las distancias entre cortes
 * consecutivos son los pesos, así que la suma es 100 por construcción y los
 * ceros (dimensiones apagadas) aparecen solos.
 */
const REPARTO = fc
  .tuple(fc.array(fc.integer({ min: 0, max: 100 }), { minLength: 5, maxLength: 5 }), fc.integer({ min: 0, max: 20 }))
  .map(([cortes, penalizacion]) => {
    const limites = [0, ...cortes.toSorted((a, b) => a - b), 100];
    const pesos: Record<string, number> = {};
    DIMENSIONES.forEach((dimension, indice) => {
      pesos[dimension] = limites[indice + 1] - limites[indice];
    });
    pesos[PENALIZACION] = penalizacion;
    return pesos;
  });

/** Lo que entrega un deslizador o un teclado: enteros, decimales y fuera de rango. */
const VALOR = fc.oneof(
  fc.integer({ min: 0, max: 100 }),
  fc.integer({ min: -50, max: 250 }),
  fc.double({ min: -50, max: 250, noNaN: true }),
);
const CLAVE = fc.constantFrom(...DIMENSIONES);
const FIJADAS = fc.subarray(DIMENSIONES).map((fijadas) => new Set(fijadas));

describe("repartirPesos · con cualquier reparto, valor y fijadas", () => {
  it("las dimensiones siguen sumando 100, en enteros no negativos", () => {
    comprobar(
      fc.property(REPARTO, CLAVE, VALOR, FIJADAS, (base, clave, valor, fijadas) => {
        const siguientes = repartirPesos(base, clave, valor, fijadas);

        expect(sumWeights(siguientes)).toBe(100);
        expect(Object.keys(siguientes).toSorted()).toEqual(Object.keys(base).toSorted());
        for (const peso of Object.values(siguientes)) {
          expect(Number.isInteger(peso)).toBe(true);
          expect(peso).toBeGreaterThanOrEqual(0);
        }
      }),
    );
  });

  it("no toca las fijadas ni la penalización", () => {
    comprobar(
      fc.property(REPARTO, CLAVE, VALOR, FIJADAS, (base, clave, valor, fijadas) => {
        const siguientes = repartirPesos(base, clave, valor, fijadas);

        for (const fijada of fijadas) {
          if (fijada !== clave) expect(siguientes[fijada]).toBe(base[fijada]);
        }
        expect(siguientes[PENALIZACION]).toBe(base[PENALIZACION]);
      }),
    );
  });

  it("la que se mueve queda en lo pedido, acotado a lo que dejan las fijadas", () => {
    comprobar(
      fc.property(REPARTO, CLAVE, VALOR, FIJADAS, (base, clave, valor, fijadas) => {
        const siguientes = repartirPesos(base, clave, valor, fijadas);
        const tope = topeDePeso(base, clave, fijadas);

        if (dimensionesLibres(base, clave, fijadas).length === 0) {
          // Sin nadie que absorba el cambio, su valor es el único que cuadra.
          expect(siguientes[clave]).toBe(tope);
        } else {
          expect(siguientes[clave]).toBe(Math.min(Math.max(Math.round(valor), 0), tope));
        }
      }),
    );
  });

  it("las libres se reparten en proporción: ninguna se aleja un punto de su cuota exacta", () => {
    // La garantía del método del resto mayor. Sin ella, «en proporción» podría
    // ser cualquier reparto que sume lo mismo.
    comprobar(
      fc.property(REPARTO, CLAVE, VALOR, FIJADAS, (base, clave, valor, fijadas) => {
        const libres = dimensionesLibres(base, clave, fijadas);
        const siguientes = repartirPesos(base, clave, valor, fijadas);
        const aRepartir = topeDePeso(base, clave, fijadas) - siguientes[clave];
        const sumaDeAntes = libres.reduce((suma, libre) => suma + base[libre], 0);

        for (const libre of libres) {
          const cuota = sumaDeAntes > 0 ? (base[libre] * aRepartir) / sumaDeAntes : aRepartir / libres.length;
          expect(Math.abs(siguientes[libre] - cuota)).toBeLessThan(1);
        }
      }),
    );
  });

  it("no invierte el orden de las libres: la que pesaba más no acaba pesando menos", () => {
    comprobar(
      fc.property(REPARTO, CLAVE, VALOR, FIJADAS, (base, clave, valor, fijadas) => {
        const libres = dimensionesLibres(base, clave, fijadas);
        const siguientes = repartirPesos(base, clave, valor, fijadas);

        for (const una of libres) {
          for (const otra of libres) {
            if (base[una] > base[otra]) expect(siguientes[una]).toBeGreaterThanOrEqual(siguientes[otra]);
          }
        }
      }),
    );
  });

  it("dejar la dimensión donde estaba no mueve nada", () => {
    // Tocar un deslizador sin arrastrarlo no puede cambiar el perfil.
    comprobar(
      fc.property(REPARTO, CLAVE, FIJADAS, (base, clave, fijadas) => {
        expect(repartirPesos(base, clave, base[clave], fijadas)).toEqual(base);
      }),
    );
  });

  it("el resultado es otro reparto válido: se puede volver a mover desde él", () => {
    comprobar(
      fc.property(REPARTO, CLAVE, VALOR, CLAVE, VALOR, (base, clave, valor, otraClave, otroValor) => {
        const primero = repartirPesos(base, clave, valor);
        const segundo = repartirPesos(primero, otraClave, otroValor);

        expect(sumWeights(segundo)).toBe(100);
        expect(Object.values(segundo).every((peso) => Number.isInteger(peso) && peso >= 0)).toBe(true);
      }),
    );
  });
});

describe("hydrateWeights · con cualquier perfil guardado", () => {
  /** Un perfil de cualquier época: le pueden faltar dimensiones y la penalización. */
  const GUARDADO = fc.dictionary(fc.constantFrom(...DIMENSIONES, PENALIZACION), fc.integer({ min: 0, max: 100 }));

  it("trae todas las dimensiones y no cambia la suma de lo guardado", () => {
    comprobar(
      fc.property(GUARDADO, (guardado) => {
        const formulario = hydrateWeights(guardado);

        for (const dimension of DIMENSIONES) expect(formulario).toHaveProperty(dimension);
        expect(sumWeights(formulario)).toBe(sumWeights(guardado));
        // Rellenar con 0 una dimensión ausente no puede tocar las que sí venían.
        for (const [clave, peso] of Object.entries(guardado)) expect(formulario[clave]).toBe(peso);
      }),
    );
  });

  it("una penalización ausente toma la global, no un 0 que la apagaría al guardar", () => {
    comprobar(
      fc.property(GUARDADO, (guardado) => {
        const esperado = PENALIZACION in guardado ? guardado[PENALIZACION] : PENALIZACIONES[PENALIZACION];
        expect(hydrateWeights(guardado)[PENALIZACION]).toBe(esperado);
      }),
    );
  });

  it("hidratar lo ya hidratado no cambia nada", () => {
    comprobar(
      fc.property(fc.option(GUARDADO, { nil: null }), (guardado) => {
        const formulario = hydrateWeights(guardado);
        expect(hydrateWeights(formulario)).toEqual(formulario);
      }),
    );
  });

  it("sumWeights no cuenta las penalizaciones", () => {
    comprobar(
      fc.property(REPARTO, (pesos) => {
        const soloDimensiones = Object.fromEntries(Object.entries(pesos).filter(([clave]) => !esPenalizacion(clave)));
        expect(sumWeights(pesos)).toBe(sumWeights(soloDimensiones));
      }),
    );
  });
});
