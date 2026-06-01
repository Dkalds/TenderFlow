/**
 * Tests for web/src/lib/filters.ts
 *
 * Covers: filtersToParams (pure function) + useFilters Zustand store actions
 */
import { describe, it, expect, beforeEach } from "vitest";
import { filtersToParams, useFilters } from "@/lib/filters";
import type { FilterValues } from "@/lib/filters";

// ---------------------------------------------------------------------------
// Helper: build a complete FilterValues object from partial overrides.
// filtersToParams receives FilterValues (state without actions).
// ---------------------------------------------------------------------------

const emptyFilters: FilterValues = {
  q: "",
  rango: { desde: null, hasta: null },
  estados: [],
  ccaas: [],
  organos: [],
  tecnologias: [],
  importeMin: null,
  comparar: false,
  rangoB: { desde: null, hasta: null },
};

function makeFilters(overrides: Partial<FilterValues> = {}): FilterValues {
  return { ...emptyFilters, ...overrides };
}

// Reset store to initial values before every test so tests are isolated
beforeEach(() => {
  useFilters.getState().resetFilters();
});

// ---------------------------------------------------------------------------
// filtersToParams
// ---------------------------------------------------------------------------

describe("filtersToParams", () => {
  it("returns an empty object for empty filters", () => {
    expect(filtersToParams(emptyFilters)).toEqual({});
  });

  it("adds 'q' when q is non-empty", () => {
    const result = filtersToParams(makeFilters({ q: "software" }));
    expect(result).toEqual({ q: "software" });
  });

  it("does NOT add 'q' when q is empty string", () => {
    const result = filtersToParams(makeFilters({ q: "" }));
    expect(result.q).toBeUndefined();
  });

  it("adds fecha_desde from rango.desde", () => {
    const result = filtersToParams(
      makeFilters({ rango: { desde: "2024-01-01", hasta: null } }),
    );
    expect(result.fecha_desde).toBe("2024-01-01");
    expect(result.fecha_hasta).toBeUndefined();
  });

  it("adds fecha_hasta from rango.hasta", () => {
    const result = filtersToParams(
      makeFilters({ rango: { desde: null, hasta: "2024-12-31" } }),
    );
    expect(result.fecha_hasta).toBe("2024-12-31");
    expect(result.fecha_desde).toBeUndefined();
  });

  it("adds both fecha_desde and fecha_hasta when both are set", () => {
    const result = filtersToParams(
      makeFilters({ rango: { desde: "2024-01-01", hasta: "2024-06-30" } }),
    );
    expect(result.fecha_desde).toBe("2024-01-01");
    expect(result.fecha_hasta).toBe("2024-06-30");
  });

  it("joins estados as comma-separated string under 'estado' key", () => {
    const result = filtersToParams(makeFilters({ estados: ["ADJ", "PUB"] }));
    expect(result.estado).toBe("ADJ,PUB");
  });

  it("omits estado when estados array is empty", () => {
    const result = filtersToParams(makeFilters({ estados: [] }));
    expect(result.estado).toBeUndefined();
  });

  it("handles a single estado value", () => {
    const result = filtersToParams(makeFilters({ estados: ["ADJ"] }));
    expect(result.estado).toBe("ADJ");
  });

  it("joins ccaas as comma-separated string under 'ccaa' key", () => {
    const result = filtersToParams(makeFilters({ ccaas: ["MD", "CT"] }));
    expect(result.ccaa).toBe("MD,CT");
  });

  it("omits ccaa when ccaas array is empty", () => {
    const result = filtersToParams(makeFilters({ ccaas: [] }));
    expect(result.ccaa).toBeUndefined();
  });

  it("joins tecnologias as comma-separated string under 'tecnologia' key", () => {
    const result = filtersToParams(
      makeFilters({ tecnologias: ["IA", "Cloud", "Ciberseguridad"] }),
    );
    expect(result.tecnologia).toBe("IA,Cloud,Ciberseguridad");
  });

  it("omits tecnologia when tecnologias array is empty", () => {
    const result = filtersToParams(makeFilters({ tecnologias: [] }));
    expect(result.tecnologia).toBeUndefined();
  });

  it("adds importe_min as string when importeMin is set", () => {
    const result = filtersToParams(makeFilters({ importeMin: 50_000 }));
    expect(result.importe_min).toBe("50000");
  });

  it("adds importe_min even when it is 0", () => {
    // 0 is not null so it should be included
    const result = filtersToParams(makeFilters({ importeMin: 0 }));
    expect(result.importe_min).toBe("0");
  });

  it("omits importe_min when importeMin is null", () => {
    const result = filtersToParams(makeFilters({ importeMin: null }));
    expect(result.importe_min).toBeUndefined();
  });

  it("does NOT include organos in params (not mapped by filtersToParams)", () => {
    const result = filtersToParams(makeFilters({ organos: ["MINISTERIO"] }));
    expect(result).not.toHaveProperty("organos");
    expect(result).not.toHaveProperty("organo");
  });

  it("combines multiple filters correctly", () => {
    const result = filtersToParams(
      makeFilters({
        q: "SAP",
        rango: { desde: "2024-01-01", hasta: "2024-12-31" },
        estados: ["PUB"],
        ccaas: ["MD"],
        tecnologias: ["ERP"],
        importeMin: 10_000,
      }),
    );
    expect(result).toEqual({
      q: "SAP",
      fecha_desde: "2024-01-01",
      fecha_hasta: "2024-12-31",
      estado: "PUB",
      ccaa: "MD",
      tecnologia: "ERP",
      importe_min: "10000",
    });
  });
});

// ---------------------------------------------------------------------------
// useFilters Zustand store — action tests
// ---------------------------------------------------------------------------

describe("useFilters store", () => {
  it("starts with empty initial state", () => {
    const state = useFilters.getState();
    expect(state.q).toBe("");
    expect(state.estados).toEqual([]);
    expect(state.ccaas).toEqual([]);
    expect(state.tecnologias).toEqual([]);
    expect(state.organos).toEqual([]);
    expect(state.importeMin).toBeNull();
    expect(state.comparar).toBe(false);
    expect(state.rango).toEqual({ desde: null, hasta: null });
    expect(state.rangoB).toEqual({ desde: null, hasta: null });
  });

  it("setQ updates the q field", () => {
    useFilters.getState().setQ("licitaciones SAP");
    expect(useFilters.getState().q).toBe("licitaciones SAP");
  });

  it("setEstados replaces the estados array", () => {
    useFilters.getState().setEstados(["ADJ", "PUB"]);
    expect(useFilters.getState().estados).toEqual(["ADJ", "PUB"]);
  });

  it("setCcaas replaces the ccaas array", () => {
    useFilters.getState().setCcaas(["MD", "CT"]);
    expect(useFilters.getState().ccaas).toEqual(["MD", "CT"]);
  });

  it("setOrganos replaces the organos array", () => {
    useFilters.getState().setOrganos(["MINDEF"]);
    expect(useFilters.getState().organos).toEqual(["MINDEF"]);
  });

  it("setTecnologias replaces the tecnologias array", () => {
    useFilters.getState().setTecnologias(["IA", "Cloud"]);
    expect(useFilters.getState().tecnologias).toEqual(["IA", "Cloud"]);
  });

  it("setImporteMin updates importeMin", () => {
    useFilters.getState().setImporteMin(25_000);
    expect(useFilters.getState().importeMin).toBe(25_000);
  });

  it("setImporteMin accepts null to clear it", () => {
    useFilters.getState().setImporteMin(25_000);
    useFilters.getState().setImporteMin(null);
    expect(useFilters.getState().importeMin).toBeNull();
  });

  it("setRango updates the date range", () => {
    useFilters.getState().setRango({ desde: "2024-01-01", hasta: "2024-06-30" });
    expect(useFilters.getState().rango).toEqual({
      desde: "2024-01-01",
      hasta: "2024-06-30",
    });
  });

  it("setComparar toggles comparison mode", () => {
    useFilters.getState().setComparar(true);
    expect(useFilters.getState().comparar).toBe(true);
  });

  it("setRangoB updates the secondary date range", () => {
    useFilters.getState().setRangoB({ desde: "2023-01-01", hasta: "2023-12-31" });
    expect(useFilters.getState().rangoB).toEqual({
      desde: "2023-01-01",
      hasta: "2023-12-31",
    });
  });

  it("resetFilters clears all filter fields to initial values", () => {
    // Dirty the store
    useFilters.getState().setQ("test");
    useFilters.getState().setEstados(["ADJ"]);
    useFilters.getState().setCcaas(["MD"]);
    useFilters.getState().setTecnologias(["IA"]);
    useFilters.getState().setImporteMin(1000);
    useFilters.getState().setComparar(true);
    useFilters.getState().setRango({ desde: "2024-01-01", hasta: "2024-12-31" });

    // Reset
    useFilters.getState().resetFilters();

    const state = useFilters.getState();
    expect(state.q).toBe("");
    expect(state.estados).toEqual([]);
    expect(state.ccaas).toEqual([]);
    expect(state.tecnologias).toEqual([]);
    expect(state.importeMin).toBeNull();
    expect(state.comparar).toBe(false);
    expect(state.rango).toEqual({ desde: null, hasta: null });
    expect(state.rangoB).toEqual({ desde: null, hasta: null });
  });

  it("successive setQ calls overwrite the previous value", () => {
    useFilters.getState().setQ("first");
    useFilters.getState().setQ("second");
    expect(useFilters.getState().q).toBe("second");
  });
});
