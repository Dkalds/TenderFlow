/**
 * Los dos hooks que le añaden estado React al modelo de la tabla.
 *
 * Se testean con `renderHook` y no montando la página: lo que hay que fijar es
 * el estado (orden, página, selección) y las derivaciones sobre la página
 * descargada, y ninguna de las dos cosas necesita el árbol de la pantalla.
 */
import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { PAGE_SIZE, type ScoringResponse } from "../_hooks/detalle-table-model";
import { useDetalleRows, useDetalleTableState } from "../_hooks/use-detalle-table";
import { PAGINATION, row } from "./detalle-fixtures";


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
