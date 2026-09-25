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
  conTotalConocido,
  conjuntoDelListado,
  mergeRows,
  type ScoringResponse,
} from "../_hooks/detalle-table-model";
import { cierreParams } from "../_hooks/use-cierre-recorte";
import { PAGINATION, row } from "./detalle-fixtures";

/* ── buildQueryParams ───────────────────────────────────────────────── */

describe("buildQueryParams", () => {
  it("la página es un cursor, no un offset (el listado por offset se retira)", () => {
    const primera = buildQueryParams({
      filterParams: { ccaa: "MD" },
      pagination: { pageIndex: 0, pageSize: 25 },
      sorting: [],
    });
    expect(primera).toEqual({ ccaa: "MD", limit: "25", with_total: "true" });

    const cuarta = buildQueryParams({
      filterParams: { ccaa: "MD" },
      pagination: { pageIndex: 3, pageSize: 25 },
      sorting: [],
      cursor: "abc",
    });
    expect(cuarta).toEqual({ ccaa: "MD", limit: "25", cursor: "abc" });
    expect(cuarta.offset).toBeUndefined();
  });

  it("el total (un COUNT(*) sobre el histórico) sólo se pide en la primera página", () => {
    // La API lo pide así (`with_total` en `listado.py`): contar en cada página
    // repetía lo que ya se sabía desde la primera.
    const conCursor = buildQueryParams({
      filterParams: {},
      pagination: { pageIndex: 1, pageSize: 25 },
      sorting: [{ id: "importe", desc: true }],
      cursor: "c1",
    });
    expect(conCursor).not.toHaveProperty("with_total");

    const sinCursor = buildQueryParams({
      filterParams: {},
      pagination: { pageIndex: 0, pageSize: 25 },
      sorting: [{ id: "importe", desc: true }],
      cursor: null,
    });
    expect(sinCursor.with_total).toBe("true");
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
    const items = [row({ id_externo: "1" }), row({ id_externo: "2", ccaa: "Madrid" }), row({ id_externo: "3" })];
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

/* ── total de las páginas sin `with_total` ─────────────────────────── */

describe("conjuntoDelListado", () => {
  const params = (extra: Record<string, string>) =>
    buildQueryParams({ filterParams: { ccaa: "MD" }, pagination: PAGINATION, sorting: [], ...extra });

  it("las páginas de un mismo listado comparten conjunto", () => {
    const primera = params({});
    const tercera = buildQueryParams({
      filterParams: { ccaa: "MD" },
      pagination: { ...PAGINATION, pageIndex: 2 },
      sorting: [],
      cursor: "c2",
    });
    expect(conjuntoDelListado(primera)).toBe(conjuntoDelListado(tercera));
  });

  it("otros filtros u otro orden son otro conjunto", () => {
    const base = conjuntoDelListado(params({}));
    const otroFiltro = buildQueryParams({ filterParams: { ccaa: "CT" }, pagination: PAGINATION, sorting: [] });
    const otroOrden = buildQueryParams({
      filterParams: { ccaa: "MD" },
      pagination: PAGINATION,
      sorting: [{ id: "importe", desc: false }],
    });
    expect(conjuntoDelListado(otroFiltro)).not.toBe(base);
    expect(conjuntoDelListado(otroOrden)).not.toBe(base);
  });

  it("no depende del orden de inserción de los parámetros", () => {
    expect(conjuntoDelListado({ a: "1", b: "2" })).toBe(conjuntoDelListado({ b: "2", a: "1" }));
  });
});

describe("conTotalConocido", () => {
  const pagina = (total?: number | null) => ({ items: [], limit: 25, has_more: true, total });

  it("respeta el total que trae la primera página", () => {
    expect(conTotalConocido(pagina(812), "A", { conjunto: "A", total: 5 }, false)?.total).toBe(812);
  });

  it("completa las páginas siguientes con el total de su conjunto", () => {
    expect(conTotalConocido(pagina(null), "A", { conjunto: "A", total: 812 }, false)?.total).toBe(812);
    expect(conTotalConocido(pagina(undefined), "A", { conjunto: "A", total: 812 }, false)?.total).toBe(812);
  });

  it("no pega a una respuesta real el total de otro conjunto", () => {
    expect(conTotalConocido(pagina(null), "B", { conjunto: "A", total: 812 }, false)?.total).toBeNull();
  });

  it("sobre datos de relleno conserva el «de N» que tenían", () => {
    // Mientras llega la primera página de un filtro nuevo se sigue enseñando la
    // página anterior: su total es el del conjunto anterior, como siempre.
    expect(conTotalConocido(pagina(null), "B", { conjunto: "A", total: 812 }, true)?.total).toBe(812);
  });

  it("sin nada que completar devuelve la misma página", () => {
    const sinTotal = pagina(null);
    expect(conTotalConocido(sinTotal, "A", null, false)).toBe(sinTotal);
    expect(conTotalConocido(undefined, "A", { conjunto: "A", total: 1 }, false)).toBeUndefined();
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
