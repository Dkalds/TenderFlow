/**
 * Las series de la vista de UTE (`_hooks/utes-series.ts`).
 *
 * Todas dan forma a lo que mandó la API —ordenar, filtrar por el buscador y
 * medir una barra contra el máximo visible— y ninguna inventa una cifra: lo que
 * se fija aquí es justo esa frontera, además del caso sin dato.
 */
import { describe, expect, it } from "vitest";

import type { Schemas } from "@/lib/api-types";
import { formatMonth } from "@/lib/utils";

import {
  FILAS_MARIPOSA,
  barrasImporteMedio,
  filasAlianzas,
  filasMariposa,
  serieEvolucion,
} from "../_hooks/utes-series";

type Miembro = Schemas["UTEMiembro"];
type SocioPar = Schemas["UTESocioPar"];
type Evolucion = Schemas["UTEEvolucion"];
type Kpis = Schemas["UTEKpis"];

const UTES: Miembro[] = [
  { nombre: "UTE Norte Sistemas - Sur Consultoría", count: 4, importe: 8_000_000 },
  { nombre: "UTE Ejemplo Digital - Informática Ágil", count: 10, importe: 2_000_000 },
  { nombre: "UTE Centro Redes - Este Datos", count: 4, importe: 16_000_000 },
];

describe("filasMariposa", () => {
  it("ordena por adjudicaciones y, a igualdad, por importe", () => {
    const filas = filasMariposa(UTES, "");
    expect(filas.map((f) => [f.puesto, f.nombre])).toEqual([
      [1, "UTE Ejemplo Digital - Informática Ágil"],
      [2, "UTE Centro Redes - Este Datos"],
      [3, "UTE Norte Sistemas - Sur Consultoría"],
    ]);
  });

  it("mide cada ala contra su propio máximo visible", () => {
    const filas = filasMariposa(UTES, "");
    expect(filas.map((f) => f.pctCount)).toEqual([100, 40, 40]);
    expect(filas.map((f) => f.pctImporte)).toEqual([12.5, 100, 50]);
    // Las cifras son las de la API, sin tocar.
    expect(filas.map((f) => [f.count, f.importe])).toEqual([
      [10, 2_000_000],
      [4, 16_000_000],
      [4, 8_000_000],
    ]);
  });

  it("el buscador filtra sin distinguir mayúsculas ni tildes, y la escala pasa a lo que queda", () => {
    const filas = filasMariposa(UTES, "CONSULTORIA");
    expect(filas).toHaveLength(1);
    expect(filas[0].nombre).toBe("UTE Norte Sistemas - Sur Consultoría");
    // El puesto es el del ranking entero, no el de la búsqueda.
    expect(filas[0].puesto).toBe(3);
    expect(filas[0].pctCount).toBe(100);
    expect(filas[0].pctImporte).toBe(100);
  });

  it("se queda con las primeras filas del ranking", () => {
    const muchas: Miembro[] = Array.from({ length: 20 }, (_, i) => ({
      nombre: `UTE ${String(i).padStart(2, "0")}`,
      count: 20 - i,
      importe: 1_000,
    }));
    const filas = filasMariposa(muchas, "");
    expect(filas).toHaveLength(FILAS_MARIPOSA);
    expect(filas.at(-1)?.nombre).toBe("UTE 11");
  });

  it("sin importes no hay ala derecha, en vez de una división por cero", () => {
    const filas = filasMariposa([{ nombre: "UTE Sin Importe", count: 2, importe: 0 }], "");
    expect(filas[0].pctCount).toBe(100);
    expect(filas[0].pctImporte).toBe(0);
  });

  it("tolera la lista todavía sin cargar", () => {
    expect(filasMariposa(undefined, "")).toEqual([]);
    expect(filasMariposa([], "algo")).toEqual([]);
  });
});

const PARES: SocioPar[] = [
  { empresa_a: "BETA", empresa_b: "GAMMA", contratos: 3, importe: 900_000 },
  { empresa_a: "ACME", empresa_b: "BETA", contratos: 9, importe: 31_200_000 },
  { empresa_a: "ACME", empresa_b: "GAMMA", contratos: 3, importe: 4_000_000 },
  { empresa_a: "DELTA", empresa_b: "EPSILON", contratos: 5, importe: 2_500_000 },
];

describe("filasAlianzas", () => {
  it("sin empresa elegida lista los pares, del más repetido al menos", () => {
    const filas = filasAlianzas(PARES, null);
    expect(filas.map((f) => [f.nombre, f.contratos, f.importe])).toEqual([
      ["ACME + BETA", 9, 31_200_000],
      ["DELTA + EPSILON", 5, 2_500_000],
      // Mismas UTE: delante el de más importe.
      ["ACME + GAMMA", 3, 4_000_000],
      ["BETA + GAMMA", 3, 900_000],
    ]);
  });

  it("cada par elige a su primera empresa", () => {
    expect(filasAlianzas(PARES, null).map((f) => f.empresa)).toEqual(["ACME", "DELTA", "ACME", "BETA"]);
  });

  it("mide la barrita contra el par más repetido de los visibles", () => {
    const filas = filasAlianzas(PARES, null);
    expect(filas[0].pct).toBe(100);
    expect(filas[1].pct).toBeCloseTo((5 / 9) * 100, 5);
  });

  it("con una empresa elegida deja sólo a sus socios, la tenga el par delante o detrás", () => {
    const filas = filasAlianzas(PARES, "BETA");
    expect(filas.map((f) => [f.nombre, f.empresa, f.contratos])).toEqual([
      ["ACME", "ACME", 9],
      ["GAMMA", "GAMMA", 3],
    ]);
    // La escala es la de sus alianzas, no la del ámbito.
    expect(filas[0].pct).toBe(100);
    expect(filas[1].pct).toBeCloseTo((3 / 9) * 100, 5);
  });

  it("da a cada fila una clave propia", () => {
    const claves = filasAlianzas(PARES, null).map((f) => f.clave);
    expect(new Set(claves).size).toBe(claves.length);
  });

  it("tolera la lista todavía sin cargar", () => {
    expect(filasAlianzas(undefined, null)).toEqual([]);
    expect(filasAlianzas([], "ACME")).toEqual([]);
  });
});

describe("serieEvolucion", () => {
  const EVOLUCION: Evolucion[] = [
    { period: "2026-02", contratos: 9, importe: 5_000_000 },
    { period: "2025-12", contratos: 3, importe: 20_000_000 },
    { period: "2026-01", contratos: 0, importe: 0 },
  ];

  it("ordena por mes y rotula cada uno de forma legible", () => {
    const { columnas } = serieEvolucion(EVOLUCION);
    expect(columnas.map((c) => c.period)).toEqual(["2025-12", "2026-01", "2026-02"]);
    expect(columnas.map((c) => c.etiqueta)).toEqual([
      formatMonth("2025-12", true),
      formatMonth("2026-01", true),
      formatMonth("2026-02", true),
    ]);
    expect(columnas[0].etiqueta).toContain("2025");
  });

  it("mide cada columna contra el máximo de su propia medida", () => {
    const { columnas, maxContratos, maxImporte } = serieEvolucion(EVOLUCION);
    expect(maxContratos).toBe(9);
    expect(maxImporte).toBe(20_000_000);
    expect(columnas[0].pctContratos).toBeCloseTo((3 / 9) * 100, 5);
    expect(columnas.slice(1).map((c) => c.pctContratos)).toEqual([0, 100]);
    expect(columnas.map((c) => c.pctImporte)).toEqual([100, 0, 25]);
    expect(columnas.map((c) => [c.contratos, c.importe])).toEqual([
      [3, 20_000_000],
      [0, 0],
      [9, 5_000_000],
    ]);
  });

  const mesesSeguidos = (cuantos: number): Evolucion[] =>
    Array.from({ length: cuantos }, (_, i) => ({
      period: `${2024 + Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, "0")}`,
      contratos: i + 1,
      importe: 1_000,
    }));
  const rotulados = (cuantos: number) =>
    serieEvolucion(mesesSeguidos(cuantos))
      .columnas.map((c, i) => (c.enEje ? i : -1))
      .filter((i) => i >= 0);

  it("rotula el eje a saltos regulares, empezando por el primer mes", () => {
    expect(rotulados(24)).toEqual([0, 6, 12, 18]);
  });

  it("no rotula un mes al que no le queda sitio a la derecha para su rótulo", () => {
    // Trece meses, de cuatro en cuatro: el último (12) se saldría del panel.
    expect(rotulados(13)).toEqual([0, 4, 8]);
  });

  it("con pocos meses reserva hueco para que las columnas no se ensanchen", () => {
    const serie = serieEvolucion(EVOLUCION);
    expect(serie.relleno).toBe(9);
    expect(serieEvolucion(Array.from({ length: 30 }, (_, i) => ({ period: `p${i}`, contratos: 1, importe: 1 }))).relleno).toBe(0);
  });

  it("sin meses no hay serie ni máximos", () => {
    expect(serieEvolucion(undefined)).toEqual({ columnas: [], maxContratos: null, maxImporte: null, relleno: 0 });
    expect(serieEvolucion([]).columnas).toEqual([]);
  });
});

describe("barrasImporteMedio", () => {
  const kpis = (ute: number, individual: number): Kpis => ({
    total_ute: 148,
    importe_ute: 282_500_000,
    ticket_medio_ute: ute,
    ticket_medio_individual: individual,
    empresas_distintas: 61,
  });

  it("pinta las dos cifras de la API, cada barra a escala de la mayor", () => {
    expect(barrasImporteMedio(kpis(1_900_000, 475_000))).toEqual([
      { clave: "ute", etiqueta: "En UTE", valor: 1_900_000, pct: 100 },
      { clave: "solitario", etiqueta: "En solitario", valor: 475_000, pct: 25 },
    ]);
  });

  it("la mayor puede ser la de en solitario", () => {
    const [ute, solitario] = barrasImporteMedio(kpis(500_000, 2_000_000));
    expect(ute.pct).toBe(25);
    expect(solitario.pct).toBe(100);
  });

  it("un importe medio de cero es la falta de contratos, no un dato: se queda sin barra ni cifra", () => {
    const [ute, solitario] = barrasImporteMedio(kpis(0, 560_000));
    expect(ute).toEqual({ clave: "ute", etiqueta: "En UTE", valor: null, pct: 0 });
    expect(solitario.valor).toBe(560_000);
    expect(solitario.pct).toBe(100);
  });

  it("sin KPIs no hay cifra en ninguna de las dos", () => {
    expect(barrasImporteMedio(undefined).map((b) => [b.valor, b.pct])).toEqual([
      [null, 0],
      [null, 0],
    ]);
  });
});
