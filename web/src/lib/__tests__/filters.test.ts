/**
 * Tests for web/src/lib/filters.ts
 *
 * Covers: filtersToParams (pure function)
 */
import { describe, it, expect } from "vitest";
import { filtersToParams, appendFiltersToPath } from "@/lib/filters";
import type { FilterValues } from "@/lib/filters";

const emptyFilters: FilterValues = {
  q: "",
  rango: { desde: null, hasta: null },
  estados: [],
  ccaas: [],
  tecnologias: [],
  importeMin: null,
  soloAbiertas: false,
};

function makeFilters(overrides: Partial<FilterValues> = {}): FilterValues {
  return { ...emptyFilters, ...overrides };
}

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
    const result = filtersToParams(makeFilters({ rango: { desde: "2024-01-01", hasta: null } }));
    expect(result.fecha_desde).toBe("2024-01-01");
    expect(result.fecha_hasta).toBeUndefined();
  });

  it("adds fecha_hasta from rango.hasta", () => {
    const result = filtersToParams(makeFilters({ rango: { desde: null, hasta: "2024-12-31" } }));
    expect(result.fecha_hasta).toBe("2024-12-31");
    expect(result.fecha_desde).toBeUndefined();
  });

  it("adds both fecha_desde and fecha_hasta when both are set", () => {
    const result = filtersToParams(makeFilters({ rango: { desde: "2024-01-01", hasta: "2024-06-30" } }));
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
    const result = filtersToParams(makeFilters({ tecnologias: ["IA", "Cloud", "Ciberseguridad"] }));
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
    const result = filtersToParams(makeFilters({ importeMin: 0 }));
    expect(result.importe_min).toBe("0");
  });

  it("omits importe_min when importeMin is null", () => {
    const result = filtersToParams(makeFilters({ importeMin: null }));
    expect(result.importe_min).toBeUndefined();
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

describe("appendFiltersToPath", () => {
  it("appends the filter query string to a plain path", () => {
    expect(appendFiltersToPath("/detalle", "?estado=PUB")).toBe("/detalle?estado=PUB");
  });

  it("returns the path untouched when there are no active filters", () => {
    expect(appendFiltersToPath("/detalle", "")).toBe("/detalle");
  });

  it("does NOT append when the path already carries its own query string", () => {
    // Deep-links that set a specific filtered view must keep overriding.
    expect(appendFiltersToPath("/detalle?lic=ABC123", "?estado=PUB")).toBe("/detalle?lic=ABC123");
  });

  it("leaves deep-links untouched even with no active filters", () => {
    expect(appendFiltersToPath("/detalle?lic=ABC123", "")).toBe("/detalle?lic=ABC123");
  });
});

describe("filtersToParams · solo_abiertas", () => {
  /**
   * Este parámetro existe porque `estado=PUB,EV` no es equivalente a "abiertas".
   * La tarjeta "Total activas" de /resumen enlazaba a `?estado=PUB,EV` mientras
   * su contador pasaba a contar todo lo no terminal: decía 12 y su listado 0.
   */
  it("emite solo_abiertas cuando está activo", () => {
    expect(filtersToParams(makeFilters({ soloAbiertas: true })).solo_abiertas).toBe("true");
  });

  it("lo omite cuando no lo está, en vez de mandar 'false'", () => {
    expect(filtersToParams(makeFilters({ soloAbiertas: false })).solo_abiertas).toBeUndefined();
  });

  it("no enumera estados: convive con un filtro de estado sin pisarlo", () => {
    const result = filtersToParams(makeFilters({ soloAbiertas: true, estados: ["ADM"] }));
    expect(result).toEqual({ solo_abiertas: "true", estado: "ADM" });
  });
});
