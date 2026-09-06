/**
 * Consulta y mezcla: qué `sort` se manda al backend, cuándo se ordena en
 * cliente y cómo se pega el scoring a la página descargada.
 *
 * Se testean las funciones puras de `_hooks/detalle-table-model.ts`, no la
 * página: montar `detalle/page.tsx` entera arrastra trece componentes de UI,
 * react-table, nuqs y tres queries, y no verifica mejor ninguna de estas reglas.
 */
import { describe, it, expect } from "vitest";
import {
  SERVER_SORT,
  buildQueryParams,
  buildScoreMap,
  mergeRows,
  type ScoringResponse,
} from "../_hooks/detalle-table-model";
import { cierreParams } from "../_hooks/use-cierre-recorte";
import { PAGINATION, row } from "./detalle-fixtures";

/* ── buildQueryParams ───────────────────────────────────────────────── */

describe("buildQueryParams", () => {
  it("traduce página y tamaño a limit/offset", () => {
    const params = buildQueryParams({
      filterParams: { ccaa: "MD" },
      pagination: { pageIndex: 3, pageSize: 25 },
      sorting: [],
    });
    expect(params).toEqual({ ccaa: "MD", limit: "25", offset: "75" });
  });

  it("no manda `sort` sin orden activo", () => {
    const params = buildQueryParams({
      filterParams: {},
      pagination: PAGINATION,
      sorting: [],
    });
    expect(params.sort).toBeUndefined();
  });

  it("omite `sort` para columnas que el backend no sabe ordenar", () => {
    // `ccaa` no está en SERVER_SORT: mandarlo sería un no-op silencioso en
    // `GET /licitaciones`, que descarta cualquier valor fuera de su mapa.
    const params = buildQueryParams({
      filterParams: {},
      pagination: PAGINATION,
      sorting: [{ id: "ccaa", desc: true }],
    });
    expect(params.sort).toBeUndefined();
    expect(SERVER_SORT.ccaa).toBeUndefined();
  });

  it("importe/título: ascendente es el sentido por defecto, descendente lleva `-`", () => {
    const asc = buildQueryParams({
      filterParams: {},
      pagination: PAGINATION,
      sorting: [{ id: "importe", desc: false }],
    });
    const desc = buildQueryParams({
      filterParams: {},
      pagination: PAGINATION,
      sorting: [{ id: "importe", desc: true }],
    });
    expect(asc.sort).toBe("importe");
    expect(desc.sort).toBe("-importe");
  });

  it("fecha_publicacion invierte el default: descendente va sin `-`", () => {
    const desc = buildQueryParams({
      filterParams: {},
      pagination: PAGINATION,
      sorting: [{ id: "fecha_publicacion", desc: true }],
    });
    const asc = buildQueryParams({
      filterParams: {},
      pagination: PAGINATION,
      sorting: [{ id: "fecha_publicacion", desc: false }],
    });
    expect(desc.sort).toBe("fecha_publicacion");
    expect(asc.sort).toBe("-fecha_publicacion");
  });

  it("los filtros globales no los pisa la paginación", () => {
    const params = buildQueryParams({
      filterParams: { q: "sap", limit: "999" },
      pagination: { pageIndex: 1, pageSize: 25 },
      sorting: [],
    });
    expect(params.q).toBe("sap");
    expect(params.limit).toBe("25");
  });
});

/* ── scoring + merge ────────────────────────────────────────────────── */

describe("buildScoreMap", () => {
  it("indexa por id_externo", () => {
    const map = buildScoreMap({
      opportunities: [
        { id_externo: "A", score: 80, band: "alta", desglose: { x: 1 } },
        { id_externo: "B", score: 20, band: "baja", desglose: {} },
      ],
    });
    expect(map.get("A")?.score).toBe(80);
    expect(map.size).toBe(2);
  });

  it("tolera undefined y respuestas sin oportunidades", () => {
    expect(buildScoreMap(undefined).size).toBe(0);
    expect(buildScoreMap({ opportunities: [] } as ScoringResponse).size).toBe(0);
  });
});

describe("mergeRows", () => {
  const scoreMap = buildScoreMap({
    opportunities: [{ id_externo: "A", score: 91, band: "alta", desglose: { importe: 5 } }],
  });

  it("adjunta score/band/desglose solo a las filas con scoring", () => {
    const merged = mergeRows({
      items: [row({ id_externo: "A" }), row({ id_externo: "B" })],
      scoreMap,
      lastViewed: 0,
      activeSort: undefined,
    });
    expect(merged[0].score).toBe(91);
    expect(merged[0].band).toBe("alta");
    expect(merged[1].score).toBeUndefined();
  });

  it("marca como nueva solo la publicada después de la última visita", () => {
    const lastViewed = new Date("2026-01-10").getTime();
    const merged = mergeRows({
      items: [
        row({ id_externo: "nueva", fecha_publicacion: "2026-02-01" }),
        row({ id_externo: "vieja", fecha_publicacion: "2025-12-01" }),
        row({ id_externo: "sin-fecha" }),
      ],
      scoreMap,
      lastViewed,
      activeSort: undefined,
    });
    expect(merged[0].isNew).toBe(true);
    expect(merged[1].isNew).toBe(false);
    // Sin fecha se resuelve a 0, que nunca es posterior a la última visita.
    expect(merged[2].isNew).toBe(false);
  });

  it("no reordena cuando el orden lo hizo el servidor", () => {
    const merged = mergeRows({
      items: [row({ id_externo: "B" }), row({ id_externo: "A" })],
      scoreMap,
      lastViewed: 0,
      activeSort: { id: "importe", desc: false },
    });
    expect(merged.map((r) => r.id_externo)).toEqual(["B", "A"]);
  });

  it("ordena en cliente las columnas que el backend no cubre", () => {
    const items = [
      row({ id_externo: "1", ccaa: "Madrid" }),
      row({ id_externo: "2", ccaa: "Aragón" }),
      row({ id_externo: "3", ccaa: "Galicia" }),
    ];
    const asc = mergeRows({
      items,
      scoreMap,
      lastViewed: 0,
      activeSort: { id: "ccaa", desc: false },
    });
    expect(asc.map((r) => r.ccaa)).toEqual(["Aragón", "Galicia", "Madrid"]);

    const desc = mergeRows({
      items,
      scoreMap,
      lastViewed: 0,
      activeSort: { id: "ccaa", desc: true },
    });
    expect(desc.map((r) => r.ccaa)).toEqual(["Madrid", "Galicia", "Aragón"]);
  });

  it("compara números como números, no como texto", () => {
    // Ordenar por `score` en cliente: con comparación de cadenas "9" iría antes
    // que "80", que es justo el bug que este camino evita.
    const map = buildScoreMap({
      opportunities: [
        { id_externo: "A", score: 9, band: "baja", desglose: {} },
        { id_externo: "B", score: 80, band: "alta", desglose: {} },
      ],
    });
    const sorted = mergeRows({
      items: [row({ id_externo: "B" }), row({ id_externo: "A" })],
      scoreMap: map,
      lastViewed: 0,
      activeSort: { id: "score", desc: false },
    });
    expect(sorted.map((r) => r.score)).toEqual([9, 80]);
  });

  it("manda los nulos al final sea cual sea el sentido", () => {
    const items = [
      row({ id_externo: "1" }),
      row({ id_externo: "2", ccaa: "Madrid" }),
      row({ id_externo: "3" }),
    ];
    const asc = mergeRows({
      items,
      scoreMap,
      lastViewed: 0,
      activeSort: { id: "ccaa", desc: false },
    });
    expect(asc[0].ccaa).toBe("Madrid");
    expect(asc.slice(1).every((r) => r.ccaa == null)).toBe(true);
  });

  it("ignora acentos y mayúsculas al ordenar texto en español", () => {
    const sorted = mergeRows({
      items: [row({ id_externo: "1", ccaa: "árbol" }), row({ id_externo: "2", ccaa: "Ana" })],
      scoreMap,
      lastViewed: 0,
      activeSort: { id: "ccaa", desc: false },
    });
    expect(sorted.map((r) => r.ccaa)).toEqual(["Ana", "árbol"]);
  });

  it("devuelve lista vacía sin items", () => {
    expect(mergeRows({ items: [], scoreMap, lastViewed: 0 })).toEqual([]);
  });
});


describe("buildQueryParams con ventana de cierre", () => {
  it("el recorte local viaja junto al ámbito global", () => {
    const params = buildQueryParams({
      filterParams: { ccaa: "Madrid", ...cierreParams(null, "2026-08-27") },
      pagination: { pageIndex: 0, pageSize: 25 },
      sorting: [],
    });
    expect(params.ccaa).toBe("Madrid");
    expect(params.cierre_hasta).toBe("2026-08-27");
  });
});
