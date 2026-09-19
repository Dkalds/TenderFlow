/**
 * F1.1 — procedimiento, provincia e importe máximo en el ámbito.
 *
 * Se fija la mitad pura: cómo viajan a la API (la misma derivación que usa el
 * prefetch en servidor) y dónde se ofrecen (sólo donde la página los declara).
 */
import { describe, expect, it } from "vitest";
import { filterParamsFromSearch, filtersToParams } from "@/lib/filter-params";
import { FILTROS_OPT_IN, pageGlobalFilterKeys, pageOptInFilterKeys } from "@/lib/navigation";
import { contarFiltros } from "@/app/(dashboard)/detalle/_hooks/use-busqueda-listado";

const VACIO = {
  q: "",
  rango: { desde: null, hasta: null },
  estados: [],
  ccaas: [],
  tecnologias: [],
  importeMin: null,
  soloAbiertas: false,
};

describe("filtros del listado → parámetros de la API", () => {
  it("viajan con los nombres que acepta GET /licitaciones", () => {
    expect(
      filtersToParams({ ...VACIO, procedimientos: ["1", "9"], provincias: ["Sevilla"], importeMax: 5e5 }),
    ).toEqual({ procedimiento: "1,9", provincia: "Sevilla", importe_max: "500000" });
  });

  it("vacíos no viajan", () => {
    expect(filtersToParams({ ...VACIO, procedimientos: [], provincias: [], importeMax: null })).toEqual({});
  });

  it("la derivación desde la URL (prefetch en servidor) da lo mismo", () => {
    const search = new URLSearchParams("procedimiento=1,9&provincia=Sevilla&importe_max=500000");
    expect(filterParamsFromSearch(search)).toEqual({
      procedimiento: "1,9",
      provincia: "Sevilla",
      importe_max: "500000",
    });
  });
});

describe("contrato por página de los filtros opt-in", () => {
  it("Detalle los declara; una pantalla analítica no", () => {
    expect(pageOptInFilterKeys("/detalle")).toEqual([...FILTROS_OPT_IN]);
    expect(pageOptInFilterKeys("/mercado")).toEqual([]);
    expect(pageOptInFilterKeys("/radar")).toEqual([]);
  });

  it("no cambian el contrato de siempre de las demás claves", () => {
    expect(pageGlobalFilterKeys("/radar")).toEqual(["tecnologia"]);
    expect(pageGlobalFilterKeys("/detalle")).toBeNull();
  });
});

describe("contarFiltros (busqueda_realizada.filtros)", () => {
  it("el periodo cuenta una vez aunque viaje en dos parámetros", () => {
    expect(contarFiltros({ fecha_desde: "2026-01-01", fecha_hasta: "2026-06-30", provincia: "Sevilla" })).toBe(2);
    expect(contarFiltros({})).toBe(0);
  });
});
