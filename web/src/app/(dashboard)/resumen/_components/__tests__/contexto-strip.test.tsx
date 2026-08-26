import { describe, it, expect } from "vitest";
import {
  compararMeses,
  mesesCerrados,
} from "@/app/(dashboard)/resumen/_components/contexto-strip";
import { formatMonth } from "@/lib/utils";

/**
 * El delta mensual del Resumen comparaba el bucket del mes **en curso** contra
 * el mes anterior completo. `por_mes` agrupa por `substr(fecha_publicacion,1,7)`,
 * así que el día 2 de cada mes la pantalla de entrada abría con un −90 % y con
 * el badge de anomalía encendido sin que hubiera pasado nada.
 */
const SERIE = [
  { mes: "2026-04", n_licitaciones: 100, importe: 1_000_000 },
  { mes: "2026-05", n_licitaciones: 110, importe: 1_100_000 },
  { mes: "2026-06", n_licitaciones: 105, importe: 1_050_000 },
  { mes: "2026-07", n_licitaciones: 108, importe: 1_080_000 },
  // Mes en curso: dos días de datos.
  { mes: "2026-08", n_licitaciones: 6, importe: 60_000 },
];

describe("mesesCerrados", () => {
  it("descarta el mes en curso", () => {
    expect(mesesCerrados(SERIE, "2026-08").map((mes) => mes.mes)).toEqual([
      "2026-04",
      "2026-05",
      "2026-06",
      "2026-07",
    ]);
  });

  it("tolera una serie ausente", () => {
    expect(mesesCerrados(undefined, "2026-08")).toEqual([]);
  });
});

describe("compararMeses", () => {
  it("compara los dos últimos meses CERRADOS, no el mes a medias", () => {
    const comparativa = compararMeses(SERIE, "2026-08");
    // jul (108) contra jun (105) = +2,86 %, no jul→ago (−94 %).
    expect(comparativa.count).toBeCloseTo(2.857, 3);
    expect(comparativa.importe).toBeCloseTo(2.857, 3);
  });

  it("dice qué meses compara en vez de un genérico «vs mes previo»", () => {
    expect(compararMeses(SERIE, "2026-08").etiqueta).toBe("jul vs jun");
  });

  it("añade el año cuando los dos meses no lo comparten", () => {
    const serie = [
      { mes: "2025-11", n_licitaciones: 10, importe: 100 },
      { mes: "2025-12", n_licitaciones: 20, importe: 200 },
      { mes: "2026-01", n_licitaciones: 30, importe: 300 },
    ];
    expect(compararMeses(serie, "2026-02").etiqueta).toBe("ene 2026 vs dic 2025");
  });

  it("no inventa un delta sin dos meses cerrados", () => {
    const comparativa = compararMeses([SERIE[4]], "2026-08");
    expect(comparativa.count).toBeUndefined();
    expect(comparativa.etiqueta).toBe("");
    expect(comparativa.anomaliaCount).toBe(false);
  });

  it("no marca anomalía por un mes en curso incompleto", () => {
    // Con el mes en curso dentro, 6 contra una media de ~105 disparaba el 2σ.
    expect(compararMeses(SERIE, "2026-08").anomaliaCount).toBe(false);
  });

  it("sí marca anomalía cuando el mes cerrado se dispara de verdad", () => {
    const serie = [
      { mes: "2026-03", n_licitaciones: 100, importe: 100 },
      { mes: "2026-04", n_licitaciones: 102, importe: 102 },
      { mes: "2026-05", n_licitaciones: 98, importe: 98 },
      { mes: "2026-06", n_licitaciones: 101, importe: 101 },
      { mes: "2026-07", n_licitaciones: 400, importe: 400 },
    ];
    expect(compararMeses(serie, "2026-08").anomaliaCount).toBe(true);
  });
});

describe("formatMonth", () => {
  it("abrevia sin el punto de «jul.»", () => {
    expect(formatMonth("2026-07")).toBe("jul");
    expect(formatMonth("2026-07", true)).toBe("jul 2026");
  });

  it("devuelve la cadena intacta si no tiene forma de mes", () => {
    expect(formatMonth("sin-fecha")).toBe("sin-fecha");
  });
});
