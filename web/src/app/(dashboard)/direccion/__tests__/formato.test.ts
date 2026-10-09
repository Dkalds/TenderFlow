/**
 * Cómo se escriben las cifras de Dirección. Las cifras llegan hechas
 * (ADR-014); lo que se fija aquí es la unidad, el signo, el color de la
 * diferencia —que decide `mejor_si`, no la clave— y adónde lleva cada corte.
 */
import { describe, expect, it } from "vitest";

import {
  enlaceDeCorte,
  formatoDelta,
  formatoIntervalo,
  lineaComparacion,
  tonoDelta,
  type Tarjeta,
} from "../_lib/formato";

function tarjeta(extra: Partial<Tarjeta>): Tarjeta {
  return { clave: "x", etiqueta: "X", unidad: "pct", universo: "U", ...extra } as Tarjeta;
}

describe("formatoDelta", () => {
  it("lleva siempre el signo y la unidad de la tarjeta", () => {
    expect(formatoDelta("pct", 0.12)).toBe("+12 pp");
    expect(formatoDelta("dias", -4.4)).toBe("−4 días");
    expect(formatoDelta("pct", 0)).toBe("±0 pp");
  });
});

describe("tonoDelta", () => {
  it("un ciclo que baja es mejor; una tasa que baja, peor", () => {
    expect(tonoDelta({ delta: -10, mejor_si: "baja" })).toBe("mejor");
    expect(tonoDelta({ delta: -0.1, mejor_si: "sube" })).toBe("peor");
    expect(tonoDelta({ delta: 0, mejor_si: "sube" })).toBe("igual");
    expect(tonoDelta({ delta: null, mejor_si: "sube" })).toBeNull();
  });
});

describe("lineaComparacion", () => {
  it("sin ventana no compara; sin base el año pasado, lo dice", () => {
    expect(lineaComparacion(tarjeta({ valor: 0.4 }))).toBeNull();
    expect(lineaComparacion(tarjeta({ valor: 0.4, n_anterior: 2, anterior: null }))).toBe(
      "Hace un año, sin base (n = 2).",
    );
    expect(lineaComparacion(tarjeta({ depende_del_periodo: false }))).toBe(
      "Foto de hoy: no depende del periodo.",
    );
  });
});

describe("formatoIntervalo", () => {
  it("redondea a puntos enteros", () => {
    expect(formatoIntervalo(0.231, 0.882)).toBe("23–88 %");
  });
});

describe("enlaceDeCorte", () => {
  it("el órgano abre su perfil y la tecnología su mercado; el resto no tiene destino", () => {
    expect(enlaceDeCorte("organo", "Ayuntamiento de Soria")).toBe(
      "/mercado?vista=organos&organo_q=Ayuntamiento%20de%20Soria",
    );
    expect(enlaceDeCorte("tecnologia", "SAP")).toBe("/mercado?vista=tecnologias&tecnologia=SAP");
    expect(enlaceDeCorte("tramo_importe", "hasta_100k")).toBeNull();
    expect(enlaceDeCorte("organo", "sin clasificar")).toBeNull();
  });
});
