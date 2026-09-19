import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { withNuqsTestingAdapter } from "nuqs/adapters/testing";
import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

/**
 * `useOrganosView` con el ámbito real de la URL (nuqs + `useFilteredQuery`
 * sin dobles). El suite de `organos-view.test.tsx` ya fija que el drill-down
 * viaja con el ámbito doblando `useFilterParams`; aquí se prueba el hook
 * entero: el deep-link `?organo_q=`, la búsqueda server-side con debounce, y
 * las derivaciones —que no inventan totales (ADR-014)—.
 */

const searchParamsRef = vi.hoisted(() => ({ actual: new URLSearchParams() }));
vi.mock("next/navigation", () => ({ useSearchParams: () => searchParamsRef.actual }));

import { useOrganosView } from "../use-organos-view";

const organo = (organo_contratacion: string, count: number, importe: number, ccaa?: string) => ({
  organo_contratacion,
  count,
  importe,
  pct: count,
  ccaa,
});

const LISTA = {
  organos: [
    organo("Ayuntamiento de Móstoles", 9, 100, "Madrid"),
    organo("Servicio Andaluz de Salud", 5, 900, "Andalucía"),
    organo("Consorci Sanitari", 2, 0, "Cataluña"),
  ],
  total_organos: 3,
  importe_total: 5_000,
  concentracion_top10: 71.5,
  treemap_breakdown: [
    { organo: "Ayuntamiento de Móstoles", tipo_contrato: "1", importe: 60 },
    { organo: "Ayuntamiento de Móstoles", tipo_contrato: "2", importe: 40 },
    { organo: "Servicio Andaluz de Salud", tipo_contrato: "9", importe: 900 },
  ],
};

const DETALLE = {
  kpis: {
    total_licitaciones: 1,
    importe_total: 1,
    importe_medio: 1,
    pct_adjudicado: 1,
    lead_time_medio: null,
    top_adjudicatario: null,
    top_adj_importe: 0,
  },
  top_adjudicatarios: [],
  estacionalidad: [],
  top_scored: [],
};

function montar(search: string, lista: unknown = LISTA) {
  searchParamsRef.actual = new URLSearchParams(search);
  const fetchMock = vi.fn().mockImplementation((...call: unknown[]) => {
    const url = callUrl(call);
    return Promise.resolve(jsonResponse(/\/analytics\/organos\/[^?]/.test(url) ? DETALLE : lista));
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Nuqs = withNuqsTestingAdapter({ searchParams: search });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <Nuqs>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </Nuqs>
  );
  const hook = renderHook(() => useOrganosView(), { wrapper });
  const urls = () => fetchMock.mock.calls.map((call) => new URL(callUrl(call), "http://x"));
  return { ...hook, urls };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("useOrganosView", () => {
  it("el ranking se pide con el ámbito de la URL de la página", async () => {
    const { result, urls } = montar("?tecnologia=SAP&estado=PUB,EV");
    await waitFor(() => expect(result.current.data).toBeDefined());

    const ranking = urls().find((u) => u.pathname === "/api/v1/analytics/organos")!;
    expect(ranking.searchParams.get("tecnologia")).toBe("SAP");
    expect(ranking.searchParams.get("estado")).toBe("PUB,EV");
    expect(ranking.searchParams.has("organo_q")).toBe(false);
  });

  it("el deep-link `?organo_q=` siembra la búsqueda y viaja al servidor", async () => {
    const { result, urls } = montar("?organo_q=Móstoles");
    expect(result.current.filter).toBe("Móstoles");
    await waitFor(() =>
      expect(urls().some((u) => u.searchParams.get("organo_q") === "Móstoles")).toBe(true),
    );
  });

  it("la búsqueda escrita espera al debounce antes de pedir", async () => {
    const { result, urls } = montar("");
    await waitFor(() => expect(result.current.data).toBeDefined());

    act(() => result.current.setFilter("salud"));
    // El filtro local se aplica al instante sobre lo que ya hay…
    expect(result.current.filteredItems.map((i) => i.organo_contratacion)).toEqual([
      "Servicio Andaluz de Salud",
    ]);
    // …y la petición al servidor llega después del debounce.
    expect(urls().some((u) => u.searchParams.get("organo_q") === "salud")).toBe(false);
    await waitFor(() => expect(urls().some((u) => u.searchParams.get("organo_q") === "salud")).toBe(true));
  });

  it("filtra sin acentos ni mayúsculas, también por CCAA", async () => {
    const { result } = montar("");
    await waitFor(() => expect(result.current.data).toBeDefined());

    act(() => result.current.setFilter("mostoles"));
    expect(result.current.filteredItems.map((i) => i.organo_contratacion)).toEqual([
      "Ayuntamiento de Móstoles",
    ]);
    act(() => result.current.setFilter("CATALUÑA"));
    expect(result.current.filteredItems.map((i) => i.organo_contratacion)).toEqual(["Consorci Sanitari"]);
  });

  it("el drill-down sólo se pide al abrir un órgano, con el nombre codificado y el ámbito", async () => {
    const { result, urls } = montar("?tecnologia=SAP");
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(urls().some((u) => u.pathname.startsWith("/api/v1/analytics/organos/"))).toBe(false);

    act(() => result.current.setSelectedOrgano("Servicio Andaluz de Salud"));
    await waitFor(() => expect(result.current.detailData).toEqual(DETALLE));

    const detalle = urls().find((u) => u.pathname.startsWith("/api/v1/analytics/organos/"))!;
    expect(decodeURIComponent(detalle.pathname)).toBe("/api/v1/analytics/organos/Servicio Andaluz de Salud");
    expect(detalle.searchParams.get("tecnologia")).toBe("SAP");
  });

  it("totales del backend, no sumas del top: y null cuando el backend no los manda", async () => {
    const { result } = montar("");
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.totalImporte).toBe(5_000);
    expect(result.current.top10Concentration).toBe(71.5);
    expect(result.current.topOrgano).toBe("Ayuntamiento de Móstoles");
    expect(result.current.maxCount).toBe(9);
    expect(result.current.top15ByImporte[0].organo_contratacion).toBe("Servicio Andaluz de Salud");

    cleanup();
    const sinTotales = montar("", { organos: [], total_organos: 0 });
    await waitFor(() => expect(sinTotales.result.current.data).toBeDefined());
    expect(sinTotales.result.current.totalImporte).toBeNull();
    expect(sinTotales.result.current.top10Concentration).toBeNull();
    expect(sinTotales.result.current.topOrgano).toBe("-");
    expect(sinTotales.result.current.maxCount).toBe(1);
  });

  it("el treemap es jerárquico con desglose y etiqueta los tipos de contrato conocidos", async () => {
    const { result } = montar("");
    await waitFor(() => expect(result.current.data).toBeDefined());

    expect(result.current.treemapData).toEqual([
      {
        name: "Ayuntamiento de Móstoles",
        children: [
          { name: "Servicios", size: 60 },
          { name: "Suministros", size: 40 },
        ],
      },
      // Un código que no está en la tabla se enseña tal cual, no se inventa.
      { name: "Servicio Andaluz de Salud", children: [{ name: "9", size: 900 }] },
    ]);
  });

  it("sin desglose el treemap es plano y deja fuera los órganos sin importe", async () => {
    const { result } = montar("", { ...LISTA, treemap_breakdown: [] });
    await waitFor(() => expect(result.current.data).toBeDefined());

    expect(result.current.treemapData).toEqual([
      { name: "Ayuntamiento de Móstoles", size: 100 },
      { name: "Servicio Andaluz de Salud", size: 900 },
    ]);
  });
});
