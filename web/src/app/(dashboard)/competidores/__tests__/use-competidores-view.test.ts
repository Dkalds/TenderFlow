/**
 * Tests de las derivaciones de Competidores (`_hooks/use-competidores-view.ts`).
 *
 * Montar la página entera exigiría siete gráficos `dynamic()` que en jsdom no
 * pintan nada útil: el test sería lento y no vería ninguna de estas reglas. Lo
 * que aquí se comprueba —qué entra en «Otros», contra qué se normaliza el radar,
 * a quién descarta el posicionamiento, cómo se recorta el mapa de calor— es
 * exactamente lo que un cambio descuidado rompe sin que la UI se queje.
 */
import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import {
  MONTH_LABELS,
  RADAR_DIMENSIONS,
  buildBarData,
  buildEstacionalidad,
  buildHeatmap,
  buildPieData,
  buildPositioningData,
  buildRadarData,
  buildScatterTop5,
  buildTreemapData,
  drillDownExtraParams,
  drillDownIds,
  filterBySearch,
  sortBajas,
  sortCompetitors,
  toggleCompareSelection,
  useCompetidoresView,
  type Competitor,
  type HeatmapEntry,
} from "../_hooks/use-competidores-view";

/* ── Fixtures ───────────────────────────────────────────────────────── */

function competitor(over: Partial<Competitor> & { nombre: string }): Competitor {
  return { count: 0, importe: 0, cuota: 0, ...over };
}

const ACME = competitor({
  nombre: "Acme Sistemas",
  nif: "A11111111",
  count: 10,
  importe: 1_000_000,
  cuota: 40,
  contratos_por_anio: 5,
  importe_medio: 100_000,
  baja_media: 20,
  pct_monopolio: 10,
});
const BETA = competitor({
  nombre: "Beta Consulting",
  nif: "B22222222",
  count: 4,
  importe: 400_000,
  cuota: 16,
  contratos_por_anio: 2,
  importe_medio: 100_000,
  baja_media: 5,
  pct_monopolio: 0,
});
const GAMMA = competitor({
  nombre: "Gamma Redes",
  nif: "C33333333",
  count: 7,
  importe: 200_000,
  cuota: 8,
});

/* ── Búsqueda ───────────────────────────────────────────────────────── */

describe("filterBySearch", () => {
  it("devuelve la lista intacta sin término de búsqueda", () => {
    const items = [ACME, BETA];
    expect(filterBySearch(items, "")).toBe(items);
  });

  it("busca por nombre sin distinguir mayúsculas", () => {
    expect(filterBySearch([ACME, BETA], "acme")).toEqual([ACME]);
  });

  it("encuentra el grupo por el NIF de cualquiera de sus identidades", () => {
    // Un competidor fusionado tiene varios CIF; buscar el de una filial tiene
    // que devolver el grupo, no cero resultados.
    const grupo = competitor({
      nombre: "Holding XY",
      nif: "X00000000",
      nifs: ["X00000000", "Y99999999"],
    });
    expect(filterBySearch([grupo, ACME], "Y99999999")).toEqual([grupo]);
  });

  it("encuentra por variante de nombre", () => {
    const grupo = competitor({
      nombre: "Holding XY",
      nombres_variantes: ["XY Servicios SL", "XY Tecnología"],
    });
    expect(filterBySearch([grupo], "xy tecnolog")).toEqual([grupo]);
  });

  it("devuelve vacío si nada casa", () => {
    expect(filterBySearch([ACME, BETA], "zzz")).toEqual([]);
  });
});

/* ── Orden ──────────────────────────────────────────────────────────── */

describe("sortCompetitors", () => {
  it("ordena texto por locale y respeta el sentido", () => {
    const asc = sortCompetitors([GAMMA, ACME, BETA], "nombre", "asc");
    expect(asc.map((c) => c.nombre)).toEqual([
      "Acme Sistemas",
      "Beta Consulting",
      "Gamma Redes",
    ]);
    const desc = sortCompetitors([GAMMA, ACME, BETA], "nombre", "desc");
    expect(desc.map((c) => c.nombre)).toEqual([
      "Gamma Redes",
      "Beta Consulting",
      "Acme Sistemas",
    ]);
  });

  it("ordena números como números", () => {
    const asc = sortCompetitors([ACME, BETA, GAMMA], "count", "asc");
    expect(asc.map((c) => c.count)).toEqual([4, 7, 10]);
  });

  it("trata como cero las métricas opcionales ausentes", () => {
    const asc = sortCompetitors([ACME, GAMMA], "contratos_por_anio", "asc");
    expect(asc[0].nombre).toBe("Gamma Redes");
  });

  it("no muta la lista de entrada", () => {
    const items = [GAMMA, ACME];
    sortCompetitors(items, "count", "asc");
    expect(items[0]).toBe(GAMMA);
  });
});

describe("toggleCompareSelection", () => {
  it("añade hasta dos", () => {
    expect(toggleCompareSelection([], "A")).toEqual(["A"]);
    expect(toggleCompareSelection(["A"], "B")).toEqual(["A", "B"]);
  });

  it("con dos ya elegidos, la más antigua cede el sitio", () => {
    expect(toggleCompareSelection(["A", "B"], "C")).toEqual(["B", "C"]);
  });

  it("volver a marcar la misma la quita", () => {
    expect(toggleCompareSelection(["A", "B"], "A")).toEqual(["B"]);
  });
});

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
    expect(radar.dataA.every((d) => Number.isFinite(d.value))).toBe(true);
    expect(radar.dataA[5].value).toBe(0);
  });
});

/* ── Treemap / posicionamiento / estacionalidad ─────────────────────── */

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

  it("copia las métricas del punto y rellena pct_monopolio ausente", () => {
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
      pct_monopolio: 0,
    });
  });

  it("vacío sin competidores", () => {
    expect(buildPositioningData([])).toEqual([]);
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

/* ── Drill-down ─────────────────────────────────────────────────────── */

describe("drill-down de un competidor agrupado", () => {
  it("sin empresa seleccionada no hay ids", () => {
    expect(drillDownIds(null)).toEqual([]);
  });

  it("deduplica empresa_id contra empresa_ids", () => {
    const grupo = competitor({ nombre: "G", empresa_id: 7, empresa_ids: [7, 8, 9] });
    expect(drillDownIds(grupo)).toEqual([7, 8, 9]);
  });

  it("una identidad suelta no manda empresa_ids", () => {
    const suelta = competitor({ nombre: "S", empresa_id: 42 });
    expect(drillDownIds(suelta)).toEqual([42]);
    expect(drillDownExtraParams([42])).toEqual({});
  });

  it("un grupo sí manda empresa_ids como lista separada por comas", () => {
    expect(drillDownExtraParams([7, 8, 9])).toEqual({ empresa_ids: "7,8,9" });
  });

  it("sin identidades no manda nada", () => {
    expect(drillDownExtraParams([])).toEqual({});
  });
});

/* ── Hook agregador ─────────────────────────────────────────────────── */

describe("useCompetidoresView", () => {
  const input = {
    competitors: [ACME, BETA, GAMMA],
    scatterData: [
      { nombre: "Acme Sistemas", ticket_medio: 1, n_organos: 2 },
      { nombre: "Beta Consulting", ticket_medio: 2, n_organos: 3 },
    ],
    heatmapCcaa: [{ empresa: "Acme Sistemas", ccaa: "Madrid", count: 4 }],
    estacionalidad: [{ mes: 3, count: 2, importe: 10 }],
    importeTotal: 2_000_000,
    bajas: [{ grupo: "Acme Sistemas", contratos: 10, baja_media_pct: 20 }],
    search: "",
    sortKey: "count" as const,
    sortDir: "desc" as const,
    selectedCompanies: [] as string[],
  };

  it("expone todas las series de la pantalla", () => {
    const { result } = renderHook(() => useCompetidoresView(input));
    expect(result.current.filteredCompetitors).toHaveLength(3);
    expect(result.current.filteredSorted.map((c) => c.count)).toEqual([10, 7, 4]);
    expect(result.current.barData[0].nombre).toBe("Acme Sistemas");
    expect(result.current.pieData.at(-1)?.name).toBe("Otros");
    expect(result.current.heatmapData.empresas).toEqual(["Acme Sistemas"]);
    expect(result.current.estacionalidadData).toHaveLength(12);
    expect(result.current.bajasSorted.rows).toHaveLength(1);
    expect(result.current.radarData).toBeNull();
  });

  it("la búsqueda propaga a tabla, dispersión y mapa de calor a la vez", () => {
    const { result } = renderHook(() =>
      useCompetidoresView({ ...input, search: "beta" }),
    );
    expect(result.current.filteredCompetitors.map((c) => c.nombre)).toEqual([
      "Beta Consulting",
    ]);
    expect(result.current.scatterData.map((p) => p.nombre)).toEqual(["Beta Consulting"]);
    expect(result.current.heatmapData.empresas).toEqual([]);
  });

  it("el top 5 de la dispersión se calcula sobre el dataset completo, no el filtrado", () => {
    // Etiquetar solo lo filtrado convertiría a cualquier rezagado en «top».
    const { result } = renderHook(() =>
      useCompetidoresView({ ...input, search: "gamma" }),
    );
    expect(result.current.scatterTop5.has("Acme Sistemas")).toBe(true);
  });

  it("con dos seleccionadas aparece el radar", () => {
    const { result } = renderHook(() =>
      useCompetidoresView({
        ...input,
        selectedCompanies: ["Acme Sistemas", "Gamma Redes"],
      }),
    );
    expect(result.current.radarData?.nameB).toBe("Gamma Redes");
  });

  it("tolera un dataset todavía sin cargar", () => {
    const { result } = renderHook(() =>
      useCompetidoresView({
        competitors: undefined,
        scatterData: undefined,
        heatmapCcaa: undefined,
        estacionalidad: undefined,
        importeTotal: undefined,
        bajas: undefined,
        search: "",
        sortKey: "count",
        sortDir: "desc",
        selectedCompanies: [],
      }),
    );
    expect(result.current.filteredCompetitors).toEqual([]);
    expect(result.current.pieData).toEqual([]);
    expect(result.current.treemapData).toEqual([]);
    expect(result.current.positioningData).toEqual([]);
    expect(result.current.bajasSorted.maxBaja).toBe(1);
  });
});
