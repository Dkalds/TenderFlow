/**
 * Tests del agregador `_hooks/use-competidores-view.ts`.
 *
 * Las reglas de cada serie se comprueban en `competidores-series.test.ts` y
 * `competidores-cruces.test.ts`; lo que se fija aquí es el cableado: que la
 * búsqueda llegue al ranking, al mapa y a la matriz a la vez pero no al titular
 * ni al reparto —que hablan del mercado, no de lo filtrado—, que el perfil
 * arranque abierto con la primera, y que la pantalla tolere un dataset todavía
 * sin cargar.
 *
 * Montar la vista entera exigiría un mapa `dynamic()` que en jsdom no pinta
 * nada útil: el test sería lento y no vería ninguna de estas reglas.
 */
import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";

import { useCompetidoresView, type CompetidoresViewInput } from "../_hooks/use-competidores-view";

import { ACME, BETA, GAMMA } from "./competidores-fixtures";

const input: CompetidoresViewInput = {
  competitors: [ACME, BETA, GAMMA],
  heatmapCcaa: [{ empresa: "Acme Sistemas", ccaa: "Madrid", count: 4 }],
  estacionalidad: [{ mes: 3, count: 2, importe: 10 }],
  totalAdjudicaciones: 50,
  totalEmpresas: 3,
  search: "",
  sortKey: "count",
  sortDir: "desc",
  metrica: "importe",
  lente: "precio",
  seleccion: null,
  perfilCerrado: false,
  rival: null,
  vigiladas: new Set<number>(),
};

describe("useCompetidoresView", () => {
  it("expone todas las series de la pantalla", () => {
    const { result } = renderHook(() => useCompetidoresView(input));
    expect(result.current.ordenados.map((c) => c.nombre)).toEqual([
      "Acme Sistemas",
      "Beta Consulting",
      "Gamma Redes",
    ]);
    expect(result.current.tabla.map((c) => c.count)).toEqual([10, 7, 4]);
    expect(result.current.concentracion.pct).toBe(64);
    expect(result.current.reparto.map((t) => t.nombre)).toEqual([
      "Acme Sistemas",
      "Beta Consulting",
      "Gamma Redes",
      // 100 − 64: lo que la API reparte entre empresas que no son estas tres.
      "Otras empresas",
    ]);
    expect(result.current.mapa.puntos.map((p) => p.nombre)).toEqual(["Acme Sistemas", "Beta Consulting"]);
    expect(result.current.heatmap.empresas).toEqual(["Acme Sistemas"]);
    expect(result.current.meses).toHaveLength(12);
    expect(result.current.duelo).toBeNull();
  });

  it("el perfil arranca abierto con la primera por la medida activa", () => {
    const { result } = renderHook(() => useCompetidoresView(input));
    expect(result.current.abierta?.nombre).toBe("Acme Sistemas");
    expect(result.current.rangoAbierta).toBe(1);
  });

  it("la medida activa reordena el ranking y recalcula el titular", () => {
    const { result } = renderHook(() => useCompetidoresView({ ...input, metrica: "count" }));
    expect(result.current.ordenados.map((c) => c.nombre)).toEqual([
      "Acme Sistemas",
      "Gamma Redes",
      "Beta Consulting",
    ]);
    expect(result.current.concentracion.pct).toBe(42);
  });

  it("la búsqueda llega al ranking, al mapa y a la matriz a la vez", () => {
    const { result } = renderHook(() => useCompetidoresView({ ...input, search: "beta" }));
    expect(result.current.ordenados.map((c) => c.nombre)).toEqual(["Beta Consulting"]);
    expect(result.current.tabla.map((c) => c.nombre)).toEqual(["Beta Consulting"]);
    expect(result.current.mapa.puntos.map((p) => p.nombre)).toEqual(["Beta Consulting"]);
    expect(result.current.heatmap.empresas).toEqual([]);
  });

  it("el titular y el reparto hablan del mercado, no de lo filtrado", () => {
    // Buscar «beta» no convierte a Beta en el 100 % del mercado.
    const { result } = renderHook(() => useCompetidoresView({ ...input, search: "beta" }));
    expect(result.current.concentracion.pct).toBe(64);
    expect(result.current.reparto[0].nombre).toBe("Acme Sistemas");
  });

  it("con la búsqueda activa el perfil sigue a lo que queda en la lista", () => {
    const { result } = renderHook(() => useCompetidoresView({ ...input, search: "beta" }));
    expect(result.current.abierta?.nombre).toBe("Beta Consulting");
  });

  it("con rival aparece el cara a cara contra el perfil abierto", () => {
    const { result } = renderHook(() =>
      useCompetidoresView({ ...input, seleccion: "Acme Sistemas", rival: "Gamma Redes" }),
    );
    expect(result.current.rival?.nombre).toBe("Gamma Redes");
    expect(result.current.duelo).toHaveLength(8);
  });

  it("con el perfil cerrado no hay ni perfil ni cara a cara", () => {
    const { result } = renderHook(() =>
      useCompetidoresView({ ...input, perfilCerrado: true, rival: "Gamma Redes" }),
    );
    expect(result.current.abierta).toBeNull();
    expect(result.current.duelo).toBeNull();
  });

  it("tolera un dataset todavía sin cargar", () => {
    const { result } = renderHook(() =>
      useCompetidoresView({
        ...input,
        competitors: undefined,
        heatmapCcaa: undefined,
        estacionalidad: undefined,
        totalAdjudicaciones: null,
        totalEmpresas: null,
      }),
    );
    expect(result.current.ordenados).toEqual([]);
    expect(result.current.reparto).toEqual([]);
    expect(result.current.mapa.puntos).toEqual([]);
    expect(result.current.concentracion.pct).toBeNull();
    expect(result.current.abierta).toBeNull();
  });
});
