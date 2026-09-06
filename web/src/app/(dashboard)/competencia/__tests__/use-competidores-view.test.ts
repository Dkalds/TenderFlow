/**
 * Tests del agregador `_hooks/use-competidores-view.ts`.
 *
 * Las reglas de cada serie se comprueban en `competidores-series.test.ts` y
 * `competidores-cruces.test.ts`; lo que se fija aquí es el cableado: que una
 * sola búsqueda llegue a la tabla, a la dispersión y al mapa de calor a la vez,
 * que el top 5 se calcule sobre el dataset completo y no sobre lo filtrado, y
 * que la pantalla tolere un dataset todavía sin cargar.
 *
 * Montar la vista entera exigiría siete gráficos `dynamic()` que en jsdom no
 * pintan nada útil: el test sería lento y no vería ninguna de estas reglas.
 */
import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";

import { useCompetidoresView } from "../_hooks/use-competidores-view";

import { ACME, BETA, GAMMA } from "./competidores-fixtures";

describe("useCompetidoresView", () => {
  const input = {
    competitors: [ACME, BETA, GAMMA],
    scatterData: [
      { nombre: "Acme Sistemas", ticket_medio: 1, n_organos: 2 },
      { nombre: "Beta Consulting", ticket_medio: 2, n_organos: 3 },
    ],
    heatmapCcaa: [{ empresa: "Acme Sistemas", ccaa: "Madrid", count: 4 }],
    estacionalidad: [{ mes: 3, count: 2, importe: 10 }],
    importeTotal: 2_000_000,
    bajas: [{ grupo: "Acme Sistemas", contratos: 10, baja_media_pct: 20 }],
    search: "",
    sortKey: "count" as const,
    sortDir: "desc" as const,
    selectedCompanies: [] as string[],
  };

  it("expone todas las series de la pantalla", () => {
    const { result } = renderHook(() => useCompetidoresView(input));
    expect(result.current.filteredCompetitors).toHaveLength(3);
    expect(result.current.filteredSorted.map((c) => c.count)).toEqual([10, 7, 4]);
    expect(result.current.barData[0].nombre).toBe("Acme Sistemas");
    expect(result.current.pieData.at(-1)?.name).toBe("Otros");
    expect(result.current.heatmapData.empresas).toEqual(["Acme Sistemas"]);
    expect(result.current.estacionalidadData).toHaveLength(12);
    expect(result.current.bajasSorted.rows).toHaveLength(1);
    expect(result.current.radarData).toBeNull();
  });

  it("la búsqueda propaga a tabla, dispersión y mapa de calor a la vez", () => {
    const { result } = renderHook(() =>
      useCompetidoresView({ ...input, search: "beta" }),
    );
    expect(result.current.filteredCompetitors.map((c) => c.nombre)).toEqual([
      "Beta Consulting",
    ]);
    expect(result.current.scatterData.map((p) => p.nombre)).toEqual(["Beta Consulting"]);
    expect(result.current.heatmapData.empresas).toEqual([]);
  });

  it("el top 5 de la dispersión se calcula sobre el dataset completo, no el filtrado", () => {
    // Etiquetar solo lo filtrado convertiría a cualquier rezagado en «top».
    const { result } = renderHook(() =>
      useCompetidoresView({ ...input, search: "gamma" }),
    );
    expect(result.current.scatterTop5.has("Acme Sistemas")).toBe(true);
  });

  it("con dos seleccionadas aparece el radar", () => {
    const { result } = renderHook(() =>
      useCompetidoresView({
        ...input,
        selectedCompanies: ["Acme Sistemas", "Gamma Redes"],
      }),
    );
    expect(result.current.radarData?.nameB).toBe("Gamma Redes");
  });

  it("tolera un dataset todavía sin cargar", () => {
    const { result } = renderHook(() =>
      useCompetidoresView({
        competitors: undefined,
        scatterData: undefined,
        heatmapCcaa: undefined,
        estacionalidad: undefined,
        importeTotal: undefined,
        bajas: undefined,
        search: "",
        sortKey: "count",
        sortDir: "desc",
        selectedCompanies: [],
      }),
    );
    expect(result.current.filteredCompetitors).toEqual([]);
    expect(result.current.pieData).toEqual([]);
    expect(result.current.treemapData).toEqual([]);
    expect(result.current.positioningData).toEqual([]);
    expect(result.current.bajasSorted.maxBaja).toBe(1);
  });
});
