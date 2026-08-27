/**
 * Tests de la lógica de la tabla de Detalle (`_hooks/use-detalle-table.ts`).
 *
 * Se testea el hook, no la página: montar `detalle/page.tsx` entera arrastra
 * trece componentes de UI, react-table, nuqs y tres queries, y no verifica mejor
 * ninguna de estas reglas. Lo que sí importa —qué `sort` se manda al backend,
 * cuándo se ordena en cliente, cómo se mezcla el scoring, qué escapa el CSV—
 * vive aquí y se comprueba directo.
 */
import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import type { SortingState } from "@tanstack/react-table";
import type { LicitacionSummary } from "@/lib/api-types";
import {
  PAGE_SIZE,
  SERVER_SORT,
  buildCsv,
  buildQueryParams,
  buildScoreMap,
  cierreLabel,
  cierreParams,
  isClientSorted,
  mergeRows,
  nextSorting,
  pageIdsOf,
  pageWindowFor,
  toggleAllPageSelection,
  toggleRowSelection,
  totalPagesFor,
  useDetalleRows,
  useDetalleTableState,
  type ScoringResponse,
} from "../_hooks/use-detalle-table";

/* ── Fixtures ───────────────────────────────────────────────────────── */

function row(overrides: Partial<LicitacionSummary> & { id_externo: string }) {
  return {
    titulo: null,
    organo_contratacion: null,
    importe: null,
    estado: null,
    fecha_publicacion: null,
    ccaa: null,
    cpv: null,
    tecnologia: null,
    ...overrides,
  } as unknown as LicitacionSummary;
}

const PAGINATION = { pageIndex: 0, pageSize: PAGE_SIZE };

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

describe("isClientSorted", () => {
  it("distingue orden de servidor de orden de página", () => {
    expect(isClientSorted([])).toBe(false);
    expect(isClientSorted([{ id: "importe", desc: false }])).toBe(false);
    expect(isClientSorted([{ id: "estado", desc: false }])).toBe(true);
  });
});

/* ── ciclo de orden y selección ─────────────────────────────────────── */

describe("nextSorting", () => {
  it("recorre asc → desc → sin orden en la misma columna", () => {
    let sorting: SortingState = [];
    sorting = nextSorting(sorting, "importe");
    expect(sorting).toEqual([{ id: "importe", desc: false }]);
    sorting = nextSorting(sorting, "importe");
    expect(sorting).toEqual([{ id: "importe", desc: true }]);
    sorting = nextSorting(sorting, "importe");
    expect(sorting).toEqual([]);
  });

  it("cambiar de columna reinicia en ascendente", () => {
    expect(nextSorting([{ id: "importe", desc: true }], "titulo")).toEqual([
      { id: "titulo", desc: false },
    ]);
  });
});

describe("selección", () => {
  it("alterna una fila quitándola del objeto al deseleccionar", () => {
    const once = toggleRowSelection({}, "A");
    expect(once).toEqual({ A: true });
    expect(toggleRowSelection(once, "A")).toEqual({});
  });

  it("no muta el estado recibido", () => {
    const current = { A: true };
    toggleRowSelection(current, "B");
    expect(current).toEqual({ A: true });
  });

  it("select-all marca toda la página sin tocar selecciones de otras páginas", () => {
    const rows = [row({ id_externo: "A" }), row({ id_externo: "B" })];
    const next = toggleAllPageSelection({ Z: true }, rows, false);
    expect(next).toEqual({ Z: true, A: true, B: true });
  });

  it("select-all sobre una página ya marcada la desmarca entera", () => {
    const rows = [row({ id_externo: "A" }), row({ id_externo: "B" })];
    const next = toggleAllPageSelection({ Z: true, A: true, B: true }, rows, true);
    expect(next).toEqual({ Z: true });
  });
});

/* ── paginación ─────────────────────────────────────────────────────── */

describe("pageIdsOf", () => {
  it("son los id_externo de las filas visibles — lo que se pide al scoring", () => {
    expect(pageIdsOf([row({ id_externo: "A" }), row({ id_externo: "B" })])).toEqual([
      "A",
      "B",
    ]);
  });

  it("lista vacía mientras la página no ha cargado", () => {
    expect(pageIdsOf(undefined)).toEqual([]);
  });

  it("descarta las filas sin id", () => {
    expect(pageIdsOf([row({ id_externo: "A" }), row({ id_externo: "" })])).toEqual(["A"]);
  });
});

describe("paginación", () => {
  it("una página como mínimo aunque no haya resultados", () => {
    expect(totalPagesFor(0, 25)).toBe(1);
    expect(totalPagesFor(26, 25)).toBe(2);
    expect(totalPagesFor(50, 25)).toBe(2);
  });

  it("la ventana se recorta contra los extremos", () => {
    expect(pageWindowFor(0, 10)).toEqual([0, 1, 2]);
    expect(pageWindowFor(5, 10)).toEqual([3, 4, 5, 6, 7]);
    expect(pageWindowFor(9, 10)).toEqual([7, 8, 9]);
    expect(pageWindowFor(0, 1)).toEqual([0]);
  });
});

/* ── CSV ────────────────────────────────────────────────────────────── */

describe("buildCsv", () => {
  it("emite la cabecera aunque no haya filas", () => {
    expect(buildCsv([])).toBe(
      "id_externo,titulo,organo_contratacion,importe,estado,fecha_publicacion,ccaa,cpv,tecnologia",
    );
  });

  it("entrecomilla los valores con coma y duplica las comillas internas", () => {
    const csv = buildCsv([
      row({ id_externo: "A", titulo: 'Obras, fase 2 con "acta"', importe: 1000 }),
    ]);
    const [, line] = csv.split("\n");
    expect(line).toContain('"Obras, fase 2 con ""acta"""');
  });

  it("escribe los nulos como celda vacía, no como «null»", () => {
    const [, line] = buildCsv([row({ id_externo: "A" })]).split("\n");
    expect(line).toBe("A,,,,,,,,");
  });

  it("exporta solo las nueve columnas del contrato, en orden", () => {
    const csv = buildCsv([
      row({ id_externo: "A", ccaa: "MD", cpv: "72000000" } as never),
    ]);
    expect(csv.split("\n")[0].split(",")).toHaveLength(9);
  });
});

/* ── hooks ──────────────────────────────────────────────────────────── */

describe("useDetalleTableState", () => {
  it("arranca sin orden, en la primera página y sin selección", () => {
    const { result } = renderHook(() =>
      useDetalleTableState({ filterParams: {}, q: "" }),
    );
    expect(result.current.sorting).toEqual([]);
    expect(result.current.pagination).toEqual({ pageIndex: 0, pageSize: PAGE_SIZE });
    expect(result.current.rowSelection).toEqual({});
    expect(result.current.clientSorted).toBe(false);
  });

  it("toggleSort recorre el ciclo y actualiza queryParams", () => {
    const { result } = renderHook(() =>
      useDetalleTableState({ filterParams: { q: "sap" }, q: "sap" }),
    );

    act(() => result.current.toggleSort("importe"));
    expect(result.current.queryParams.sort).toBe("importe");
    expect(result.current.clientSorted).toBe(false);

    act(() => result.current.toggleSort("importe"));
    expect(result.current.queryParams.sort).toBe("-importe");

    act(() => result.current.toggleSort("importe"));
    expect(result.current.queryParams.sort).toBeUndefined();
  });

  it("una columna de cliente marca clientSorted y no viaja al backend", () => {
    const { result } = renderHook(() =>
      useDetalleTableState({ filterParams: {}, q: "" }),
    );
    act(() => result.current.toggleSort("estado"));
    expect(result.current.clientSorted).toBe(true);
    expect(result.current.queryParams.sort).toBeUndefined();
  });

  it("cambiar la búsqueda global vuelve a la primera página", () => {
    const { result, rerender } = renderHook(
      ({ q }: { q: string }) => useDetalleTableState({ filterParams: { q }, q }),
      { initialProps: { q: "" } },
    );

    act(() => result.current.setPagination({ pageIndex: 6, pageSize: PAGE_SIZE }));
    expect(result.current.queryParams.offset).toBe("150");

    rerender({ q: "sap" });
    expect(result.current.pagination.pageIndex).toBe(0);
    expect(result.current.queryParams.offset).toBe("0");
  });

  it("no reinicia la página si la búsqueda no cambia", () => {
    const { result, rerender } = renderHook(
      ({ q }: { q: string }) => useDetalleTableState({ filterParams: {}, q }),
      { initialProps: { q: "sap" } },
    );
    act(() => result.current.setPagination({ pageIndex: 2, pageSize: PAGE_SIZE }));
    rerender({ q: "sap" });
    expect(result.current.pagination.pageIndex).toBe(2);
  });

  it("toggleRow alterna la selección", () => {
    const { result } = renderHook(() =>
      useDetalleTableState({ filterParams: {}, q: "" }),
    );
    act(() => result.current.toggleRow("A"));
    expect(result.current.rowSelection).toEqual({ A: true });
    act(() => result.current.toggleRow("A"));
    expect(result.current.rowSelection).toEqual({});
  });
});

describe("useDetalleRows", () => {
  const items = [
    row({ id_externo: "A", ccaa: "Madrid" }),
    row({ id_externo: "B", ccaa: "Galicia" }),
  ];
  const scoring: ScoringResponse = {
    opportunities: [{ id_externo: "A", score: 70, band: "media", desglose: {} }],
  };

  function setup(rowSelection: Record<string, boolean> = {}) {
    const state = { current: rowSelection };
    const hook = renderHook(() =>
      useDetalleRows({
        items,
        total: 60,
        scoring,
        lastViewed: 0,
        activeSort: undefined,
        pagination: PAGINATION,
        rowSelection: state.current,
        setRowSelection: (updater) => {
          state.current =
            typeof updater === "function" ? updater(state.current) : updater;
        },
      }),
    );
    return { hook, state };
  }

  it("calcula totalPages y la ventana desde el total del servidor", () => {
    const { hook } = setup();
    expect(hook.result.current.totalPages).toBe(3);
    expect(hook.result.current.pageWindow).toEqual([0, 1, 2]);
  });

  it("mezcla el scoring en las filas", () => {
    const { hook } = setup();
    expect(hook.result.current.mergedRows[0].score).toBe(70);
    expect(hook.result.current.mergedRows[1].score).toBeUndefined();
  });

  it("selectedItems son filas reales, no ids sueltos", () => {
    const { hook } = setup({ A: true, fantasma: true });
    expect(hook.result.current.selectedIds).toEqual(["A", "fantasma"]);
    expect(hook.result.current.selectedItems.map((r) => r.id_externo)).toEqual(["A"]);
  });

  it("allPageSelected es falso con la página vacía", () => {
    const { result } = renderHook(() =>
      useDetalleRows({
        items: [],
        total: 0,
        scoring: undefined,
        lastViewed: 0,
        pagination: PAGINATION,
        rowSelection: {},
        setRowSelection: () => {},
      }),
    );
    expect(result.current.allPageSelected).toBe(false);
    expect(result.current.totalPages).toBe(1);
  });

  it("allPageSelected solo con todas las filas visibles marcadas", () => {
    expect(setup({ A: true }).hook.result.current.allPageSelected).toBe(false);
    expect(setup({ A: true, B: true }).hook.result.current.allPageSelected).toBe(true);
  });

  it("toggleAllPage marca la página entera y luego la limpia", () => {
    const { hook, state } = setup();
    act(() => hook.result.current.toggleAllPage());
    expect(state.current).toEqual({ A: true, B: true });

    const marcada = setup({ A: true, B: true });
    act(() => marcada.hook.result.current.toggleAllPage());
    expect(marcada.state.current).toEqual({});
  });

  it("tolera `items` y `total` sin definir mientras carga", () => {
    const { result } = renderHook(() =>
      useDetalleRows({
        items: undefined,
        total: undefined,
        scoring: null,
        lastViewed: 0,
        pagination: PAGINATION,
        rowSelection: {},
        setRowSelection: () => {},
      }),
    );
    expect(result.current.mergedRows).toEqual([]);
    expect(result.current.totalPages).toBe(1);
  });
});

/* ── ventana de cierre ──────────────────────────────────────────────── */

describe("cierreParams", () => {
  it("pasa las dos cotas con los nombres del contrato de la API", () => {
    expect(cierreParams("2026-08-26", "2026-08-27")).toEqual({
      cierre_desde: "2026-08-26",
      cierre_hasta: "2026-08-27",
    });
  });

  it("acepta una sola cota", () => {
    expect(cierreParams(null, "2026-08-27")).toEqual({ cierre_hasta: "2026-08-27" });
    expect(cierreParams("2026-08-26", null)).toEqual({ cierre_desde: "2026-08-26" });
  });

  it("descarta lo que no sea YYYY-MM-DD", () => {
    // El backend responde 422 a un formato inválido y un 422 vacía la tabla:
    // una URL editada a mano no puede tumbar la pantalla.
    expect(cierreParams("27/08/2026", "mañana")).toEqual({});
    expect(cierreParams(null, null)).toEqual({});
  });
});

describe("cierreLabel", () => {
  it("declara el recorte activo y devuelve null cuando no hay ninguno", () => {
    expect(cierreLabel({ cierre_desde: "2026-08-26", cierre_hasta: "2026-08-27" })).toBe(
      "Cierra 2026-08-26 → 2026-08-27",
    );
    expect(cierreLabel({ cierre_hasta: "2026-08-27" })).toBe("Cierra hasta 2026-08-27");
    expect(cierreLabel({ cierre_desde: "2026-08-26" })).toBe("Cierra desde 2026-08-26");
    expect(cierreLabel({})).toBeNull();
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
