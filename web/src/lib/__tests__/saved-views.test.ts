import { describe, it, expect, vi } from "vitest";
import { snapshotFilters, applySnapshot } from "@/lib/saved-views";
import type { FilterValues, FiltersState } from "@/lib/filters";

const baseValues: FilterValues = {
  q: "",
  rango: { desde: null, hasta: null },
  estados: [],
  ccaas: [],
  tecnologias: [],
  importeMin: null,
};

function makeFilters(overrides: Partial<FilterValues> = {}): FilterValues {
  return { ...baseValues, ...overrides };
}

describe("snapshotFilters", () => {
  it("serialises an empty filter state to valid JSON", () => {
    const json = snapshotFilters(baseValues);
    expect(() => JSON.parse(json)).not.toThrow();
  });

  it("round-trips q field", () => {
    const snap = snapshotFilters(makeFilters({ q: "software" }));
    expect(JSON.parse(snap).q).toBe("software");
  });

  it("round-trips rango field", () => {
    const rango = { desde: "2024-01-01", hasta: "2024-06-30" };
    const snap = snapshotFilters(makeFilters({ rango }));
    expect(JSON.parse(snap).rango).toEqual(rango);
  });

  it("round-trips estados array", () => {
    const snap = snapshotFilters(makeFilters({ estados: ["ADJ", "PUB"] }));
    expect(JSON.parse(snap).estados).toEqual(["ADJ", "PUB"]);
  });

  it("round-trips ccaas array", () => {
    const snap = snapshotFilters(makeFilters({ ccaas: ["MD", "CT"] }));
    expect(JSON.parse(snap).ccaas).toEqual(["MD", "CT"]);
  });

  it("round-trips tecnologias array", () => {
    const snap = snapshotFilters(makeFilters({ tecnologias: ["SAP"] }));
    expect(JSON.parse(snap).tecnologias).toEqual(["SAP"]);
  });

  it("round-trips importeMin value", () => {
    const snap = snapshotFilters(makeFilters({ importeMin: 50000 }));
    expect(JSON.parse(snap).importeMin).toBe(50000);
  });
});

describe("applySnapshot", () => {
  function makeMockState(): FiltersState {
    return {
      ...baseValues,
      setQ: vi.fn(),
      setRango: vi.fn(),
      setEstados: vi.fn(),
      setCcaas: vi.fn(),
      setTecnologias: vi.fn(),
      setImporteMin: vi.fn(),
      setComparar: vi.fn(),
      setRangoB: vi.fn(),
      resetFilters: vi.fn(),
      comparar: false,
      rangoB: { desde: null, hasta: null },
    };
  }

  it("calls all setters when the snapshot is valid", () => {
    const filters = makeMockState();
    const json = snapshotFilters(makeFilters({ q: "SAP", estados: ["ADJ"] }));
    applySnapshot(filters, json);
    expect(filters.setQ).toHaveBeenCalledWith("SAP");
    expect(filters.setEstados).toHaveBeenCalledWith(["ADJ"]);
  });

  it("uses defaults for missing fields in snapshot", () => {
    const filters = makeMockState();
    applySnapshot(filters, JSON.stringify({}));
    expect(filters.setQ).toHaveBeenCalledWith("");
    expect(filters.setRango).toHaveBeenCalledWith({ desde: null, hasta: null });
    expect(filters.setEstados).toHaveBeenCalledWith([]);
    expect(filters.setCcaas).toHaveBeenCalledWith([]);
    expect(filters.setTecnologias).toHaveBeenCalledWith([]);
    expect(filters.setImporteMin).toHaveBeenCalledWith(null);
  });

  it("does nothing when snapshot JSON is invalid", () => {
    const filters = makeMockState();
    applySnapshot(filters, "not-valid-json{{");
    expect(filters.setQ).not.toHaveBeenCalled();
  });

  it("restores rango correctly", () => {
    const filters = makeMockState();
    const rango = { desde: "2024-01-01", hasta: "2024-12-31" };
    applySnapshot(filters, JSON.stringify({ rango }));
    expect(filters.setRango).toHaveBeenCalledWith(rango);
  });

  it("restores importeMin correctly", () => {
    const filters = makeMockState();
    applySnapshot(filters, JSON.stringify({ importeMin: 10000 }));
    expect(filters.setImporteMin).toHaveBeenCalledWith(10000);
  });
});
