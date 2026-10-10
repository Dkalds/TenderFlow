import { describe, expect, it } from "vitest";
import { partirLista, sumWeights } from "../_lib/pesos";
import { repartirPesos, topeDePeso } from "../_lib/reparto-pesos";

/**
 * El reparto es lo que permite guardar sin cuadrar seis números a mano, así
 * que su única promesa es dura: salga lo que salga, las dimensiones suman 100
 * y las fijadas no se tocan.
 */

const PESOS = {
  importe: 20,
  plazo: 15,
  competencia: 20,
  margen: 20,
  afinidad: 15,
  senal_tecnica: 10,
  organo_anula_frecuente: 8,
};

describe("repartirPesos", () => {
  it("reparte la diferencia en proporción a lo que tenía cada dimensión", () => {
    // Importe pasa de 20 a 60: quedan 40 para las otras cinco, que sumaban 80.
    const siguientes = repartirPesos(PESOS, "importe", 60);

    expect(siguientes).toMatchObject({ importe: 60, competencia: 10, margen: 10, senal_tecnica: 5 });
    // 15 × 40/80 = 7,5 para plazo y para afinidad: el punto que sobra del
    // redondeo va a la que aparece antes.
    expect(siguientes.plazo).toBe(8);
    expect(siguientes.afinidad).toBe(7);
    expect(sumWeights(siguientes)).toBe(100);
  });

  it("suma 100 para cualquier valor de cualquier dimensión", () => {
    for (const clave of ["importe", "plazo", "competencia", "margen", "afinidad", "senal_tecnica"]) {
      for (let valor = 0; valor <= 100; valor += 1) {
        const siguientes = repartirPesos(PESOS, clave, valor);
        expect(sumWeights(siguientes)).toBe(100);
        expect(Object.values(siguientes).every((peso) => Number.isInteger(peso) && peso >= 0)).toBe(true);
      }
    }
  });

  it("no toca las penalizaciones", () => {
    expect(repartirPesos(PESOS, "importe", 90).organo_anula_frecuente).toBe(8);
  });

  it("no toca las fijadas y acota lo que puede tomar la que se mueve", () => {
    const fijadas = new Set(["plazo", "margen"]);

    const siguientes = repartirPesos(PESOS, "importe", 100, fijadas);

    expect(topeDePeso(PESOS, "importe", fijadas)).toBe(65);
    expect(siguientes).toMatchObject({ importe: 65, plazo: 15, margen: 20 });
    expect(siguientes).toMatchObject({ competencia: 0, afinidad: 0, senal_tecnica: 0 });
  });

  it("si las demás estaban a cero, reparte a partes iguales", () => {
    const todoEnImporte = { importe: 100, plazo: 0, competencia: 0, margen: 0, afinidad: 0, senal_tecnica: 0 };

    const siguientes = repartirPesos(todoEnImporte, "importe", 50);

    expect(siguientes).toEqual({ importe: 50, plazo: 10, competencia: 10, margen: 10, afinidad: 10, senal_tecnica: 10 });
  });

  it("partir de los pesos de antes del gesto conserva las proporciones al ir y volver", () => {
    // Arrastrar hasta 100 y soltar en 20: con el reparto encadenado paso a
    // paso las demás acababan iguales entre sí; desde la base vuelven a su sitio.
    const ida = repartirPesos(PESOS, "importe", 100);
    expect(ida).toMatchObject({ importe: 100, plazo: 0, competencia: 0 });

    expect(repartirPesos(PESOS, "importe", 20)).toEqual(PESOS);
  });

  it("sin ninguna dimensión libre, la que se mueve se queda con lo único que cuadra", () => {
    const fijadas = new Set(["plazo", "competencia", "margen", "afinidad", "senal_tecnica"]);

    expect(repartirPesos(PESOS, "importe", 5, fijadas).importe).toBe(20);
  });
});

describe("partirLista", () => {
  it("separa por comas, punto y coma o saltos de línea y descarta lo vacío", () => {
    expect(partirLista(" sap, s/4hana;abap\n\n  fiori  ,")).toEqual(["sap", "s/4hana", "abap", "fiori"]);
  });
});
