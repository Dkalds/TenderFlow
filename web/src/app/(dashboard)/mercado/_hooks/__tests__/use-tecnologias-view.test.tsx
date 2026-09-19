import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { withNuqsTestingAdapter } from "nuqs/adapters/testing";
import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

/**
 * `useTecnologiasView` con el ámbito **real**: nuqs leyendo la URL de la
 * página y `useFilteredQuery` sin dobles. Es el flujo que el P1 de cobertura
 * daba por descubierto —filtros nuqs usados desde una pantalla, no sólo
 * `lib/filters.ts` en abstracto—, y a la vez fija las transformaciones de la
 * vista: todas pivotan u ordenan lo que el backend ya calculó (ADR-014), y el
 * único agregado local es el bucket «Otros» del donut.
 */

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));

import { useTecnologiasView } from "../use-tecnologias-view";

const tech = (tecnologia: string, count: number, importe: number) => ({
  tecnologia,
  count,
  importe,
  importe_medio: importe / Math.max(count, 1),
  pct: count,
  pct_adjudicado: 50,
});

const AGREGADO = {
  tecnologias: [
    tech("SAP", 40, 4_000_000),
    tech("Oracle", 30, 0),
    ...Array.from({ length: 10 }, (_, i) => tech(`T${i}`, 10 - i, 1_000 * (i + 1))),
  ],
  sin_clasificar: 5,
  n_tecnologias: 12,
  tecnologia_lider: "SAP",
  lider_count: 40,
  importe_medio_global: 1,
  tasa_adjudicacion_media: 50,
  cross_organo: [
    { organo: "Org A", tecnologia: "SAP", count: 5 },
    { organo: "Org B", tecnologia: "SAP", count: 2 },
    { organo: "Org B", tecnologia: "Oracle", count: 9 },
  ],
  cross_geo: [
    { ccaa: "Madrid", tecnologia: "SAP", count: 3 },
    { ccaa: "Cataluña", tecnologia: "SAP", count: 1 },
    { ccaa: "Cataluña", tecnologia: "Oracle", count: 6 },
  ],
  evolucion_mensual: [
    { mes: "2026-02", tecnologia: "SAP", count: 2, importe: 200 },
    { mes: "2026-01", tecnologia: "SAP", count: 1, importe: 100 },
    { mes: "2026-01", tecnologia: "Oracle", count: 4, importe: 50 },
  ],
};

const DETALLE = { tecnologia: "SAP", n: 1, importe_total: 10, importe_medio: 10, items: [] };
const SCORING = { opportunities: [{ id: "X-1", titulo: "Top", importe: 1, score: 90 }] };

function cuerpo(url: string): unknown {
  if (url.includes("/tecnologias/detail")) return DETALLE;
  if (url.includes("/analytics/scoring")) return SCORING;
  return AGREGADO;
}

function montar(search: string) {
  const fetchMock = vi
    .fn()
    .mockImplementation((...call: unknown[]) => Promise.resolve(jsonResponse(cuerpo(callUrl(call)))));
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Nuqs = withNuqsTestingAdapter({ searchParams: search });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <Nuqs>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </Nuqs>
  );
  const hook = renderHook(() => useTecnologiasView(), { wrapper });
  const urls = () => fetchMock.mock.calls.map((call) => callUrl(call));
  return { ...hook, urls };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("useTecnologiasView", () => {
  it("el ámbito de la URL de la página viaja en las dos peticiones iniciales", async () => {
    const { result, urls } = montar("?tecnologia=SAP&ccaa=MD&solo_abiertas=true&vista=tecnologias");
    await waitFor(() => expect(result.current.data).toBeDefined());

    const agregado = urls().find((u) => u.startsWith("/api/v1/analytics/tecnologias"))!;
    const scoring = urls().find((u) => u.startsWith("/api/v1/analytics/scoring"))!;
    for (const url of [agregado, scoring]) {
      const params = new URL(url, "http://x").searchParams;
      expect(params.get("tecnologia")).toBe("SAP");
      expect(params.get("ccaa")).toBe("MD");
      expect(params.get("solo_abiertas")).toBe("true");
      // `vista` es de la página, no del ámbito: no llega a la API.
      expect(params.has("vista")).toBe(false);
    }
    expect(new URL(scoring, "http://x").searchParams.get("limit")).toBe("20");
    // Sin tecnología elegida en la vista, el detalle no se pide.
    expect(urls().some((u) => u.includes("/tecnologias/detail"))).toBe(false);
  });

  it("el detalle se pide al elegir tecnología, con el resto del ámbito", async () => {
    const { result, urls } = montar("?ccaa=MD");
    await waitFor(() => expect(result.current.data).toBeDefined());

    act(() => result.current.setSelectedTech("SAP"));
    await waitFor(() => expect(result.current.detalle).toEqual(DETALLE));

    const detalle = new URL(urls().find((u) => u.includes("/tecnologias/detail"))!, "http://x");
    expect(detalle.searchParams.get("tecnologia")).toBe("SAP");
    expect(detalle.searchParams.get("ccaa")).toBe("MD");
  });

  it("sin ámbito la petición sale sin query", async () => {
    const { result, urls } = montar("");
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(urls()).toContain("/api/v1/analytics/tecnologias");
  });

  it("el donut agrupa en «Otros» lo que pasa de diez y conserva los totales", async () => {
    const { result } = montar("");
    await waitFor(() => expect(result.current.data).toBeDefined());

    const donut = result.current.donutData;
    expect(donut).toHaveLength(10);
    expect(donut.slice(0, 2).map((d) => d.tecnologia)).toEqual(["SAP", "Oracle"]);
    const otros = donut[9];
    expect(otros.tecnologia).toBe("Otros");
    const suma = (xs: { count: number }[]) => xs.reduce((s, x) => s + x.count, 0);
    expect(suma(donut)).toBe(suma(AGREGADO.tecnologias));
  });

  it("las barras recortan a quince, excluyen importe cero y van en orden ascendente para el eje", async () => {
    const { result } = montar("");
    await waitFor(() => expect(result.current.data).toBeDefined());

    const { volumeBar, importeBar } = result.current;
    expect(volumeBar.length).toBeLessThanOrEqual(15);
    expect(volumeBar.at(-1)?.tecnologia).toBe("SAP");
    expect(importeBar.some((b) => b.tecnologia === "Oracle")).toBe(false);
    expect(importeBar.at(-1)?.tecnologia).toBe("SAP");
    expect(volumeBar.every((b) => b._color.startsWith("hsl("))).toBe(true);
  });

  it("gira la evolución mensual y cambia de métrica sin volver a pedir", async () => {
    const { result, urls } = montar("");
    await waitFor(() => expect(result.current.data).toBeDefined());
    const pedidas = urls().length;

    expect(result.current.evolTechs).toEqual(["Oracle", "SAP"]);
    expect(result.current.evolData).toEqual([
      { mes: "2026-01", SAP: 1, Oracle: 4 },
      { mes: "2026-02", SAP: 2 },
    ]);

    act(() => result.current.setTrendMetric("importe"));
    expect(result.current.evolData[0]).toEqual({ mes: "2026-01", SAP: 100, Oracle: 50 });
    expect(urls()).toHaveLength(pedidas);
  });

  it("el heatmap y el reparto geográfico ordenan por totales del backend", async () => {
    const { result } = montar("");
    await waitFor(() => expect(result.current.data).toBeDefined());

    const heatmap = result.current.heatmap!;
    expect(heatmap.techs).toEqual(["Oracle", "SAP"]);
    expect(heatmap.organos).toEqual(["Org B", "Org A"]);
    expect(heatmap.cell.get("SAP||Org A")).toBe(5);
    expect(heatmap.maxVal).toBe(9);

    expect(result.current.geoTechs).toEqual(["Oracle", "SAP"]);
    expect(result.current.geoData.map((g) => g.ccaa)).toEqual(["Cataluña", "Madrid"]);
  });

  it("el filtro local es por subcadena sin mayúsculas y no pide nada", async () => {
    const { result, urls } = montar("");
    await waitFor(() => expect(result.current.data).toBeDefined());
    const pedidas = urls().length;

    act(() => result.current.setFilter("orac"));
    expect(result.current.filteredItems.map((i) => i.tecnologia)).toEqual(["Oracle"]);
    expect(urls()).toHaveLength(pedidas);
    expect(result.current.scoredItems).toEqual(SCORING.opportunities);
  });

  it("sin cruces no hay heatmap: no se fabrica una matriz vacía", async () => {
    const fetchMock = vi.fn().mockImplementation((...call: unknown[]) =>
      Promise.resolve(
        jsonResponse(
          callUrl(call).includes("scoring") ? SCORING : { ...AGREGADO, cross_organo: [], tecnologias: [] },
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const Nuqs = withNuqsTestingAdapter({ searchParams: "" });
    const { result } = renderHook(() => useTecnologiasView(), {
      wrapper: ({ children }) => (
        <Nuqs>
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        </Nuqs>
      ),
    });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.heatmap).toBeNull();
    expect(result.current.donutData).toEqual([]);
  });
});
