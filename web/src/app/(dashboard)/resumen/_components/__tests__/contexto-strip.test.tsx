import { describe, it, expect } from "vitest";
import {
  celdaSalud,
  coberturaSinMedir,
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
    expect(mesesCerrados(SERIE, "2026-08").map((mes) => mes.mes)).toEqual(["2026-04", "2026-05", "2026-06", "2026-07"]);
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

/**
 * «Oferta única 93,1 %» y «PYME adjudicataria 0,7 %» estaban en la tira de salud
 * competitiva como hechos del mercado. No lo eran: el numerador cuenta las
 * adjudicaciones que traen `n_ofertas_recibidas`/`es_pyme` y la republicación
 * masiva de PSCP no las trae, así que el porcentaje describía la fuente. Lo que
 * estos tests fijan es que la cifra **no llega a pintarse** mientras el backend
 * no acredite sobre cuántas filas va — y que la celda diga cuánto le falta, en
 * el mismo tono que «sin dos meses cerrados que comparar».
 */
describe("celdaSalud", () => {
  const GLOSA = "adjudicaciones con 1 oferta";

  it("se abstiene cuando el backend no manda cobertura", () => {
    const celda = celdaSalud(93.1, undefined, GLOSA);
    expect(celda.value).toBe("—");
    expect(celda.value).not.toContain("93");
    expect(celda.hint).toBe("sin cobertura medida del dato de origen");
  });

  it("se abstiene con cobertura baja y dice exactamente cuánta hay", () => {
    const celda = celdaSalud(
      93.1,
      {
        base: 5780,
        universo: 170000,
        cobertura_pct: 3.4,
        umbral_pct: 50,
        suficiente: false,
      },
      GLOSA,
    );
    expect(celda.value).toBe("—");
    expect(celda.hint).toBe("solo 3,4% de las adjudicaciones traen el dato");
  });

  it("no confunde «cobertura 0 %» con «cobertura sin medir»", () => {
    const celda = celdaSalud(93.1, { cobertura_pct: 0, suficiente: false }, GLOSA);
    expect(celda.hint).toBe("solo 0,0% de las adjudicaciones traen el dato");
  });

  it("ignora un `suficiente` ausente aunque la cobertura sea alta", () => {
    // Backend viejo sirviendo el campo a medias: el default es abstenerse.
    const celda = celdaSalud(93.1, { cobertura_pct: 88.2 }, GLOSA);
    expect(celda.value).toBe("—");
  });

  it("pinta el porcentaje solo cuando el backend lo avala, con la cobertura al pie", () => {
    const celda = celdaSalud(
      41.5,
      {
        base: 150000,
        universo: 170000,
        cobertura_pct: 88.2,
        umbral_pct: 50,
        suficiente: true,
      },
      GLOSA,
    );
    expect(celda.value).toBe("41,5%");
    expect(celda.hint).toBe(`${GLOSA} · cobertura 88,2%`);
  });
});

/**
 * La segunda mitad de la decisión: abstenerse no es lo mismo cuando se sabe
 * cuánta cobertura hay que cuando no se sabe. Con cobertura medida y baja, la
 * celda tiene algo que contar y se queda. Sin medir —que es lo que devuelve hoy
 * `overview_adjudicaciones_indicadores`— sólo puede repetir «no sé» en todas las
 * cargas, así que la celda se retira de la tira y el motivo se dice una vez en
 * el pie de la sección.
 */
describe("coberturaSinMedir", () => {
  it("es cierto cuando el backend no manda cobertura", () => {
    expect(coberturaSinMedir(undefined)).toBe(true);
  });

  it("es cierto cuando la manda pero sin `cobertura_pct` (el caso de hoy)", () => {
    expect(coberturaSinMedir({ umbral_pct: 50, suficiente: false })).toBe(true);
    expect(coberturaSinMedir({ cobertura_pct: null, umbral_pct: 50 })).toBe(true);
  });

  it("es falso con cobertura medida, aunque sea cero o insuficiente", () => {
    expect(coberturaSinMedir({ cobertura_pct: 0, suficiente: false })).toBe(false);
    expect(coberturaSinMedir({ cobertura_pct: 3.4, suficiente: false })).toBe(false);
    expect(coberturaSinMedir({ cobertura_pct: 88.2, suficiente: true })).toBe(false);
  });
});
