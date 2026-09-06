/**
 * Tests de las series de `_hooks/competidores-series.ts` que cruzan dos
 * dimensiones: mapa de calor empresa × CCAA, radar de dos competidores y
 * posicionamiento baja media × importe medio.
 *
 * Van juntas porque comparten el modo de mentir: en un cruce, un cero por dato
 * ausente no se lee como «sin dato» sino como una posición —el vértice pegado
 * al centro, el punto en el origen—, y eso es una afirmación que el dataset no
 * hace. Cada uno de estos tests fija dónde se decidió abstenerse.
 */
import { describe, it, expect } from "vitest";

import {
  RADAR_DIMENSIONS,
  buildHeatmap,
  buildPositioningData,
  buildRadarData,
} from "../_hooks/competidores-series";
import type { HeatmapEntry } from "../_hooks/competidores-types";

import { ACME, BETA, GAMMA, competitor } from "./competidores-fixtures";

/* ── Mapa de calor ──────────────────────────────────────────────────── */

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

/* ── Radar ──────────────────────────────────────────────────────────── */

describe("buildRadarData", () => {
  const pool = [ACME, BETA, GAMMA];

  it("null salvo con exactamente dos seleccionadas", () => {
    expect(buildRadarData([], pool)).toBeNull();
    expect(buildRadarData(["Acme Sistemas"], pool)).toBeNull();
    expect(buildRadarData(["A", "B", "C"], pool)).toBeNull();
  });

  it("null si el dataset aún no llegó", () => {
    expect(buildRadarData(["Acme Sistemas", "Beta Consulting"], undefined)).toBeNull();
  });

  it("null si alguna seleccionada ya no está en los datos", () => {
    // Cambiar el filtro global puede dejar fuera a una elegida antes; pintar el
    // radar con una sola sería comparar contra nada.
    expect(buildRadarData(["Acme Sistemas", "Fantasma SL"], pool)).toBeNull();
  });

  it("normaliza contra el máximo del mercado, no contra los dos elegidos", () => {
    // Beta tiene 4 de los 10 contratos del líder: 40, no 100.
    const radar = buildRadarData(["Acme Sistemas", "Beta Consulting"], pool)!;
    expect(radar.dataA[0].value).toBe(100);
    expect(radar.dataB[0].value).toBe(40);
  });

  it("emite las seis dimensiones en orden para ambos", () => {
    const radar = buildRadarData(["Acme Sistemas", "Beta Consulting"], pool)!;
    expect(radar.dataA.map((d) => d.dimension)).toEqual([...RADAR_DIMENSIONS]);
    expect(radar.dataB).toHaveLength(6);
    expect(radar.nameA).toBe("Acme Sistemas");
    expect(radar.nameB).toBe("Beta Consulting");
  });

  it("una métrica ausente en todo el dataset no divide por cero", () => {
    const sinBaja = [
      competitor({ nombre: "A", count: 1, importe: 1, cuota: 1 }),
      competitor({ nombre: "B", count: 1, importe: 1, cuota: 1 }),
    ];
    const radar = buildRadarData(["A", "B"], sinBaja)!;
    // Los ejes que SÍ tienen dato siguen siendo números finitos: el `max(…, 1)`
    // sigue evitando la división por cero, que es lo que este test vigila.
    expect(radar.dataA.slice(0, 3).every((d) => Number.isFinite(d.value))).toBe(true);
  });

  it("un eje sin dato sale `null`, no pegado al centro", () => {
    // Este test afirmaba `value === 0` para el eje ausente, y con eso blindaba
    // el problema en vez de detectarlo: en un radar el 0 es el vértice pegado
    // al centro, que se lee como «el peor del mercado en esa dimensión». Es una
    // afirmación, y justo la contraria de lo que se sabe. Recharts deja hueco
    // con `null`.
    const sinBaja = [
      competitor({ nombre: "A", count: 1, importe: 1, cuota: 1 }),
      competitor({ nombre: "B", count: 1, importe: 1, cuota: 1 }),
    ];
    const radar = buildRadarData(["A", "B"], sinBaja)!;
    expect(radar.dataA[5].value).toBeNull();
    expect(radar.dataB[5].value).toBeNull();
  });
});

/* ── Posicionamiento ────────────────────────────────────────────────── */

describe("buildPositioningData", () => {
  it("descarta a quien no tiene baja media o importe medio", () => {
    // Un punto en (0,0) por dato ausente afirmaría «no baja y contratos
    // minúsculos», que el dataset no dice.
    const points = buildPositioningData([ACME, GAMMA]);
    expect(points.map((p) => p.nombre)).toEqual(["Acme Sistemas"]);
  });

  it("descarta importe medio cero", () => {
    const cero = competitor({ nombre: "Z", baja_media: 5, importe_medio: 0 });
    expect(buildPositioningData([cero])).toEqual([]);
  });

  it("copia las métricas del punto y propaga pct_monopolio ausente", () => {
    // Antes esperaba `pct_monopolio: 0`, y ese cero llegaba al tooltip como
    // «% Monopolio: 0,0 %»: una empresa sin dato de ofertantes se presentaba
    // como la más disputada del mercado. El propio `buildPositioningData`
    // descarta los puntos sin ambos ejes para no afirmar lo que el dataset no
    // dice, y hacía justo eso con la tercera dimensión.
    const sinMonopolio = competitor({
      nombre: "Z",
      baja_media: 12,
      importe_medio: 5000,
      count: 3,
    });
    expect(buildPositioningData([sinMonopolio])[0]).toEqual({
      nombre: "Z",
      baja_media: 12,
      importe_medio: 5000,
      count: 3,
      pct_monopolio: null,
    });
  });

  it("un pct_monopolio real sí se copia", () => {
    // La distinción que importa: 0 es un dato, ausente es otra cosa.
    const conCero = competitor({
      nombre: "Z",
      baja_media: 12,
      importe_medio: 5000,
      count: 3,
      pct_monopolio: 0,
    });
    expect(buildPositioningData([conCero])[0].pct_monopolio).toBe(0);
  });

  it("vacío sin competidores", () => {
    expect(buildPositioningData([])).toEqual([]);
  });
});
