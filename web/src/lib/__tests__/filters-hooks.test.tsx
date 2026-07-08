/**
 * Tests for the nuqs-backed hooks in web/src/lib/filters.ts
 *
 * Covers: useFilters (reads + setters), useFilterParams, useFiltersQueryString,
 * useWithFilters. The pure functions (filtersToParams, appendFiltersToPath) are
 * covered in filters.test.ts.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, act, waitFor, cleanup } from "@testing-library/react";
import { withNuqsTestingAdapter } from "nuqs/adapters/testing";

// useFiltersQueryString / useWithFilters read next/navigation's useSearchParams
// directly (not via nuqs), so we control it through a hoisted mutable ref
// (vi.mock factories are hoisted above regular module-level declarations).
const { searchParamsRef } = vi.hoisted(() => ({
  searchParamsRef: { current: new URLSearchParams() },
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => searchParamsRef.current,
}));

import {
  useFilters,
  useFilterParams,
  useFiltersQueryString,
  useWithFilters,
} from "@/lib/filters";

afterEach(() => {
  cleanup();
});

const FULL_URL =
  "?q=obras&estado=PUB,ADJ&ccaa=MD&tecnologia=IA&importe_min=1000" +
  "&comparar=true&fecha_desde=2024-01-01&fecha_hasta=2024-12-31" +
  "&rango_b_desde=2023-01-01&rango_b_hasta=2023-12-31";

describe("useFilters", () => {
  it("reads and derives all filter values from the URL", () => {
    const { result } = renderHook(() => useFilters(), {
      wrapper: withNuqsTestingAdapter({ searchParams: FULL_URL }),
    });
    expect(result.current.q).toBe("obras");
    expect(result.current.estados).toEqual(["PUB", "ADJ"]);
    expect(result.current.ccaas).toEqual(["MD"]);
    expect(result.current.tecnologias).toEqual(["IA"]);
    expect(result.current.importeMin).toBe(1000);
    expect(result.current.comparar).toBe(true);
    expect(result.current.rango).toEqual({ desde: "2024-01-01", hasta: "2024-12-31" });
    expect(result.current.rangoB).toEqual({ desde: "2023-01-01", hasta: "2023-12-31" });
  });

  it("defaults to empty values when the URL has no filters", () => {
    const { result } = renderHook(() => useFilters(), {
      wrapper: withNuqsTestingAdapter({ searchParams: "" }),
    });
    expect(result.current.q).toBe("");
    expect(result.current.estados).toEqual([]);
    expect(result.current.importeMin).toBeNull();
    expect(result.current.comparar).toBe(false);
    expect(result.current.rango).toEqual({ desde: null, hasta: null });
  });
});

describe("useFilterParams", () => {
  it("returns API-ready params derived from the URL filters", () => {
    const { result } = renderHook(() => useFilterParams(), {
      wrapper: withNuqsTestingAdapter({ searchParams: FULL_URL }),
    });
    expect(result.current).toMatchObject({
      q: "obras",
      estado: "PUB,ADJ",
      ccaa: "MD",
      tecnologia: "IA",
      importe_min: "1000",
    });
  });
});

describe("useFiltersQueryString / useWithFilters", () => {
  it("keeps only recognised filter keys in the query string", () => {
    searchParamsRef.current = new URLSearchParams("q=obras&estado=PUB&foo=bar");
    const { result } = renderHook(() => useFiltersQueryString());
    expect(result.current).toContain("q=obras");
    expect(result.current).toContain("estado=PUB");
    expect(result.current).not.toContain("foo");
  });

  it("returns an empty string when no filters are active", () => {
    searchParamsRef.current = new URLSearchParams();
    const { result } = renderHook(() => useFiltersQueryString());
    expect(result.current).toBe("");
  });

  it("appends active filters to a plain path", () => {
    searchParamsRef.current = new URLSearchParams("q=obras");
    const { result } = renderHook(() => useWithFilters());
    expect(result.current("/detalle")).toBe("/detalle?q=obras");
  });

  it("leaves deep-linked paths (with their own query) untouched", () => {
    searchParamsRef.current = new URLSearchParams("q=obras");
    const { result } = renderHook(() => useWithFilters());
    expect(result.current("/detalle?lic=ABC")).toBe("/detalle?lic=ABC");
  });
});

// Kept last: exercising the setters pushes writes onto nuqs' shared global
// update queue, so we fully drain it here rather than let it bleed into the
// read-only tests above.
describe("useFilters setters", () => {
  it("invokes every setter without throwing and updates the URL", async () => {
    const onUrlUpdate = vi.fn();
    const { result } = renderHook(() => useFilters(), {
      wrapper: withNuqsTestingAdapter({ onUrlUpdate }),
    });
    await act(async () => {
      result.current.setQ("nuevo");
      result.current.setEstados(["PUB"]);
      result.current.setCcaas(["MD"]);
      result.current.setTecnologias(["IA"]);
      result.current.setImporteMin(5000);
      result.current.setImporteMin(null);
      result.current.setComparar(true);
      result.current.setComparar(false);
      result.current.setRango({ desde: "2024-01-01", hasta: "2024-02-01" });
      result.current.setRango({ desde: null, hasta: null });
      result.current.setRangoB({ desde: "2023-01-01", hasta: null });
      result.current.resetFilters();
    });
    await waitFor(() => expect(onUrlUpdate).toHaveBeenCalled());
  });
});
