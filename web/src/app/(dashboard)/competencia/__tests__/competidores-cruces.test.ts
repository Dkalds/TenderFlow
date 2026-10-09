/**
 * Tests de `_hooks/competidores-cruces.ts`, las series que cruzan dos
 * dimensiones: la matriz empresa × CCAA y el mapa de competidores con sus dos
 * lentes.
 *
 * Van juntas porque comparten el modo de mentir: en un cruce, un cero por dato
 * ausente no se lee como «sin dato» sino como una posición —el punto pegado al
 * eje—, y eso es una afirmación que el dataset no hace. Cada uno de estos tests
 * fija dónde se decidió abstenerse.
 */
import { describe, it, expect } from "vitest";

import { buildHeatmap, buildMapa } from "../_hooks/competidores-cruces";
import type { HeatmapEntry } from "../_hooks/competidores-types";

import { ACME, BETA, GAMMA, competitor } from "./competidores-fixtures";

/* ── Matriz empresa × CCAA ──────────────────────────────────────────── */

describe("buildHeatmap", () => {
  const entries: HeatmapEntry[] = [
    { empresa: "Acme", ccaa: "Madrid", count: 5 },
    { empresa: "Acme", ccaa: "Galicia", count: 3 },
    { empresa: "Beta", ccaa: "Madrid", count: 9 },
  ];

  it("modelo vacío sin datos", () => {
    expect(buildHeatmap(undefined, "")).toEqual({
      empresas: [],
      ccaas: [],
      matrix: {},
      max: 0,
    });
    expect(buildHeatmap([], "").max).toBe(0);
  });

  it("ordena empresas por total y deja las CCAA alfabéticas", () => {
    const model = buildHeatmap(entries, "");
    // Acme suma 8 contratos, Beta 9: Beta va primero.
    expect(model.empresas).toEqual(["Beta", "Acme"]);
    expect(model.ccaas).toEqual(["Galicia", "Madrid"]);
  });

  it("el máximo es el de una celda, no el total de una empresa", () => {
    expect(buildHeatmap(entries, "").max).toBe(9);
  });

  it("indexa la matriz por empresa y CCAA", () => {
    const { matrix } = buildHeatmap(entries, "");
    expect(matrix.Acme.Madrid).toBe(5);
    expect(matrix.Beta.Galicia).toBeUndefined();
  });

  it("recorta a las diez empresas con más contratos", () => {
    const many: HeatmapEntry[] = Array.from({ length: 14 }, (_, i) => ({
      empresa: `E${i}`,
      ccaa: "Madrid",
      count: i + 1,
    }));
    const model = buildHeatmap(many, "");
    expect(model.empresas).toHaveLength(10);
    expect(model.empresas).not.toContain("E0");
  });

  it("la búsqueda filtra por nombre de empresa", () => {
    const model = buildHeatmap(entries, "acme");
    expect(model.empresas).toEqual(["Acme"]);
    expect(model.max).toBe(5);
  });
});

/* ── Mapa de competidores ───────────────────────────────────────────── */

describe("buildMapa", () => {
  const sinMarcas = { abierta: null, vigiladas: new Set<number>() };

  describe("lente de precio", () => {
    it("baja media en horizontal e importe medio en vertical", () => {
      const { puntos } = buildMapa([ACME, BETA], "precio", sinMarcas);
      expect(puntos.map((p) => [p.nombre, p.x, p.y])).toEqual([
        ["Acme Sistemas", 20, 100_000],
        ["Beta Consulting", 5, 100_000],
      ]);
    });

    it("descarta a quien no tiene baja media o importe medio, y lo cuenta", () => {
      // Un punto en (0,0) por dato ausente afirmaría «no baja y contratos
      // minúsculos», que el dataset no dice.
      const mapa = buildMapa([ACME, GAMMA], "precio", sinMarcas);
      expect(mapa.puntos.map((p) => p.nombre)).toEqual(["Acme Sistemas"]);
      expect(mapa.sinDato).toBe(1);
    });

    it("un importe medio a cero es el valor por defecto del backend, no un dato", () => {
      const cero = competitor({ nombre: "Z", baja_media: 5, importe_medio: 0 });
      expect(buildMapa([cero], "precio", sinMarcas).puntos).toEqual([]);
    });

    it("una baja media de 0 sí se dibuja: es un dato", () => {
      const sinBaja = competitor({ nombre: "Z", baja_media: 0, importe_medio: 5000 });
      expect(buildMapa([sinBaja], "precio", sinMarcas).puntos).toHaveLength(1);
    });
  });

  describe("lente de clientes", () => {
    it("órganos distintos en horizontal y peso del primero en vertical", () => {
      const { puntos } = buildMapa([ACME, BETA], "clientes", sinMarcas);
      expect(puntos.map((p) => [p.nombre, p.x, p.y])).toEqual([
        ["Acme Sistemas", 6, 30],
        ["Beta Consulting", 2, 75],
      ]);
    });

    it("descarta a quien no trae órganos", () => {
      const mapa = buildMapa([ACME, GAMMA], "clientes", sinMarcas);
      expect(mapa.puntos.map((p) => p.nombre)).toEqual(["Acme Sistemas"]);
      expect(mapa.sinDato).toBe(1);
    });
  });

  it("las medianas salen de los puntos dibujados", () => {
    const tercero = competitor({ nombre: "Z", baja_media: 11, importe_medio: 40_000, cuota: 1 });
    const mapa = buildMapa([ACME, BETA, tercero, GAMMA], "precio", sinMarcas);
    // Gamma no se dibuja, así que no cuenta: bajas 20, 5 y 11.
    expect(mapa.medianaX).toBe(11);
    expect(mapa.medianaY).toBe(100_000);
  });

  it("con menos de dos puntos no hay medianas que partan el plano", () => {
    const mapa = buildMapa([ACME], "precio", sinMarcas);
    expect(mapa.medianaX).toBeNull();
    expect(mapa.medianaY).toBeNull();
  });

  it("el tamaño del punto es la cuota de la API", () => {
    expect(buildMapa([ACME], "precio", sinMarcas).puntos[0].cuota).toBe(40);
  });

  it("solo llevan nombre las seis de más cuota, la abierta y las vigiladas", () => {
    const muchas = Array.from({ length: 9 }, (_, i) =>
      competitor({ nombre: `E${i}`, empresa_id: 100 + i, cuota: 9 - i, baja_media: i, importe_medio: 1000 + i }),
    );
    const mapa = buildMapa(muchas, "precio", { abierta: "E7", vigiladas: new Set([108]) });
    const conNombre = mapa.puntos.filter((p) => p.etiqueta !== "").map((p) => p.nombre);
    expect(conNombre).toEqual(["E0", "E1", "E2", "E3", "E4", "E5", "E7", "E8"]);
  });

  it("marca la abierta y las vigiladas", () => {
    const mapa = buildMapa([ACME, BETA], "precio", { abierta: "Beta Consulting", vigiladas: new Set([1]) });
    expect(mapa.puntos.map((p) => [p.seleccionado, p.vigilada])).toEqual([
      [false, true],
      [true, false],
    ]);
  });

  it("una agrupación está vigilada si lo está cualquiera de sus identidades", () => {
    const grupo = competitor({
      nombre: "Holding XY",
      empresa_id: 7,
      empresa_ids: [7, 8, 9],
      baja_media: 10,
      importe_medio: 1000,
    });
    expect(buildMapa([grupo], "precio", { abierta: null, vigiladas: new Set([9]) }).puntos[0].vigilada).toBe(true);
  });

  it("vacío sin competidores", () => {
    expect(buildMapa([], "precio", sinMarcas)).toEqual({ puntos: [], medianaX: null, medianaY: null, sinDato: 0 });
  });
});
