/**
 * Tests de las series de reparto y ranking de `_hooks/competidores-series.ts`:
 * tarta de cuota, barras, top 5 de la dispersión, treemap, estacionalidad y
 * ranking de bajas.
 *
 * Lo que se comprueba aquí es lo que un cambio descuidado rompe sin que la UI
 * se queje: qué entra en «Otros», dónde se recorta cada ranking y qué pasa con
 * una empresa que no trae el dato.
 */
import { describe, it, expect } from "vitest";

import {
  MONTH_LABELS,
  buildBarData,
  buildEstacionalidad,
  buildPieData,
  buildScatterTop5,
  buildTreemapData,
  sortBajas,
} from "../_hooks/competidores-series";

import { ACME, BETA, competitor } from "./competidores-fixtures";

/* ── Tarta ──────────────────────────────────────────────────────────── */

describe("buildPieData", () => {
  const many = Array.from({ length: 12 }, (_, i) =>
    competitor({ nombre: `E${i}`, importe: (12 - i) * 1000, count: 1 }),
  );

  it("vacío sin competidores", () => {
    expect(buildPieData([], "", 1000)).toEqual([]);
  });

  it("sin búsqueda, «Otros» es la cola del mercado total, no solo la visible", () => {
    // El backend recorta la lista a `limit`; usar la suma de lo devuelto como
    // total pintaría una cuota inflada para el top 10.
    const pie = buildPieData(many, "", 1_000_000);
    const top10Importe = many
      .slice(0, 10)
      .reduce((s, c) => s + c.importe, 0);
    const otros = pie.find((s) => s.name === "Otros");
    expect(pie).toHaveLength(11);
    expect(otros?.value).toBe(1_000_000 - top10Importe);
  });

  it("con búsqueda, «Otros» solo agrega la cola de lo filtrado", () => {
    const pie = buildPieData(many, "E", 1_000_000);
    const cola = many.slice(10).reduce((s, c) => s + c.importe, 0);
    expect(pie.find((s) => s.name === "Otros")?.value).toBe(cola);
  });

  it("omite «Otros» cuando no queda cola", () => {
    const pie = buildPieData([ACME, BETA], "acme", undefined);
    expect(pie.map((s) => s.name)).not.toContain("Otros");
  });

  it("nunca emite un «Otros» negativo si el total llega por debajo", () => {
    const pie = buildPieData([ACME], "", 1);
    expect(pie.map((s) => s.name)).not.toContain("Otros");
  });

  it("recorta los nombres largos para la leyenda", () => {
    const nombre = "Consorcio Nacional de Infraestructuras y Servicios Integrales";
    const largo = competitor({ nombre, importe: 10 });
    // `truncate` corta a 25 y añade la elipsis: 26 caracteres visibles.
    expect(buildPieData([largo], "x", undefined)[0].name).toBe(
      `${nombre.slice(0, 25)}…`,
    );
  });
});

/* ── Barras / dispersión ────────────────────────────────────────────── */

describe("buildBarData", () => {
  it("ordena por número de adjudicaciones y recorta a 20", () => {
    const many = Array.from({ length: 25 }, (_, i) =>
      competitor({ nombre: `E${i}`, count: i }),
    );
    const bars = buildBarData(many);
    expect(bars).toHaveLength(20);
    expect(bars[0].count).toBe(24);
  });
});

describe("buildScatterTop5", () => {
  it("son los cinco de mayor importe", () => {
    const many = Array.from({ length: 8 }, (_, i) =>
      competitor({ nombre: `E${i}`, importe: i * 100 }),
    );
    const top5 = buildScatterTop5(many);
    expect(top5.size).toBe(5);
    expect(top5.has("E7")).toBe(true);
    expect(top5.has("E2")).toBe(false);
  });

  it("conjunto vacío sin datos", () => {
    expect(buildScatterTop5(undefined).size).toBe(0);
    expect(buildScatterTop5([]).size).toBe(0);
  });
});

/* ── Treemap / estacionalidad ───────────────────────────────────────── */

describe("buildTreemapData", () => {
  it("vacío sin competidores", () => {
    expect(buildTreemapData([])).toEqual([]);
  });

  it("top 20 por importe, con el nombre recortado", () => {
    const many = Array.from({ length: 25 }, (_, i) =>
      competitor({ nombre: `Empresa con nombre larguísimo ${i}`, importe: i, count: 1 }),
    );
    const nodes = buildTreemapData(many);
    expect(nodes).toHaveLength(20);
    expect(nodes[0].size).toBe(24);
    // `truncate` corta a 22 y añade la elipsis.
    expect(nodes[0].name).toBe("Empresa con nombre lar…");
  });
});

describe("buildEstacionalidad", () => {
  it("vacío cuando el endpoint no manda la serie", () => {
    expect(buildEstacionalidad(undefined)).toEqual([]);
    expect(buildEstacionalidad([])).toEqual([]);
  });

  it("rellena los doce meses aunque solo lleguen algunos", () => {
    const serie = buildEstacionalidad([
      { mes: 1, count: 4, importe: 100 },
      { mes: 12, count: 2, importe: 50 },
    ]);
    expect(serie).toHaveLength(12);
    expect(serie.map((p) => p.mes)).toEqual(MONTH_LABELS);
    expect(serie[0]).toEqual({ mes: "Ene", count: 4, importe: 100 });
    expect(serie[5]).toEqual({ mes: "Jun", count: 0, importe: 0 });
    expect(serie[11].count).toBe(2);
  });
});

/* ── Bajas ──────────────────────────────────────────────────────────── */

describe("sortBajas", () => {
  it("modelo neutro sin datos: maxBaja 1 para no dividir por cero", () => {
    expect(sortBajas(undefined)).toEqual({ rows: [], maxBaja: 1 });
  });

  it("descarta las que no tienen baja media", () => {
    const model = sortBajas([
      { grupo: "A", contratos: 6, baja_media_pct: null },
      { grupo: "B", contratos: 8, baja_media_pct: 12 },
    ]);
    expect(model.rows.map((r) => r.grupo)).toEqual(["B"]);
  });

  it("ordena de más agresiva a menos y expone el máximo", () => {
    const model = sortBajas([
      { grupo: "A", contratos: 6, baja_media_pct: 5 },
      { grupo: "B", contratos: 8, baja_media_pct: 30 },
      { grupo: "C", contratos: 9, baja_media_pct: 18 },
    ]);
    expect(model.rows.map((r) => r.grupo)).toEqual(["B", "C", "A"]);
    expect(model.maxBaja).toBe(30);
  });

  it("recorta a doce filas", () => {
    const model = sortBajas(
      Array.from({ length: 20 }, (_, i) => ({
        grupo: `G${i}`,
        contratos: 5,
        baja_media_pct: i,
      })),
    );
    expect(model.rows).toHaveLength(12);
  });
});
