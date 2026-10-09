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

/** El total del ámbito que el titular toma del recuento general. */
const OVERVIEW = { total_licitaciones: 1_284, importe_medio: 379_000 };

function montar(search: string, lista: unknown = LISTA) {
  searchParamsRef.actual = new URLSearchParams(search);
  const fetchMock = vi.fn().mockImplementation((...call: unknown[]) => {
    const url = callUrl(call);
    if (/\/analytics\/organos\/[^?]/.test(url)) return Promise.resolve(jsonResponse(DETALLE));
    if (url.includes("/analytics/overview")) return Promise.resolve(jsonResponse(OVERVIEW));
    return Promise.resolve(jsonResponse(lista));
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

  it("el perfil arranca con el primero del ranking; abrir otro pide su detalle con el nombre codificado y el ámbito", async () => {
    const { result, urls } = montar("?tecnologia=SAP");
    await waitFor(() => expect(result.current.data).toBeDefined());

    // Sin nada elegido, el perfil es el del órgano con más licitaciones.
    expect(result.current.organoAbierto).toBe("Ayuntamiento de Móstoles");
    expect(result.current.rangoAbierto).toBe(1);
    await waitFor(() => expect(result.current.detailData).toEqual(DETALLE));

    act(() => result.current.abrirOrgano("Servicio Andaluz de Salud"));
    const esSas = (u: URL) =>
      decodeURIComponent(u.pathname) === "/api/v1/analytics/organos/Servicio Andaluz de Salud";
    await waitFor(() => expect(urls().some(esSas)).toBe(true));

    const detalle = urls().find(esSas)!;
    expect(detalle.searchParams.get("tecnologia")).toBe("SAP");
    expect(result.current.rangoAbierto).toBe(2);

    // Cerrar el perfil no vuelve a abrir el primero.
    act(() => result.current.cerrarPerfil());
    expect(result.current.organoAbierto).toBeNull();
  });

  it("totales de la API, no sumas del top: y null cuando la API no los manda", async () => {
    const { result } = montar("");
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.importeTotal).toBe(5_000);
    expect(result.current.totalOrganos).toBe(3);
    expect(result.current.concentracionTop10).toBe(71.5);
    // Por licitaciones, la concentración es la cifra de la API sobre todo el ámbito.
    expect(result.current.concentracion).toEqual({ pct: 71.5, parcial: false });
    expect(result.current.totalLicitaciones).toBe(1_284);

    cleanup();
    const sinTotales = montar("", { organos: [], total_organos: 0 });
    await waitFor(() => expect(sinTotales.result.current.data).toBeDefined());
    expect(sinTotales.result.current.importeTotal).toBeNull();
    expect(sinTotales.result.current.concentracionTop10).toBeNull();
    expect(sinTotales.result.current.concentracion).toEqual({ pct: null, parcial: false });
    // Sin órganos no hay perfil que abrir.
    expect(sinTotales.result.current.organoAbierto).toBeNull();
  });

  it("por importe, la concentración se calcula sobre la lista recibida y se declara parcial", async () => {
    const { result } = montar("");
    await waitFor(() => expect(result.current.data).toBeDefined());

    act(() => result.current.setMetrica("importe"));
    // (100 + 900 + 0) sobre los 5.000 de importe total del ámbito.
    expect(result.current.concentracion).toEqual({ pct: 20, parcial: true });
    // El ranking y el perfil siguen a la medida: el primero pasa a ser el de más importe.
    expect(result.current.mariposa.map((f) => f.organo)).toEqual([
      "Servicio Andaluz de Salud",
      "Ayuntamiento de Móstoles",
      "Consorci Sanitari",
    ]);
    expect(result.current.organoAbierto).toBe("Servicio Andaluz de Salud");
  });

  it("la mariposa escala cada ala a su máximo; el mapa trae medianas, etiquetas y el seleccionado", async () => {
    const { result } = montar("");
    await waitFor(() => expect(result.current.data).toBeDefined());

    const filas = result.current.mariposa;
    expect(filas.map((f) => f.organo)).toEqual([
      "Ayuntamiento de Móstoles",
      "Servicio Andaluz de Salud",
      "Consorci Sanitari",
    ]);
    expect(filas.map((f) => Math.round(f.pctCount))).toEqual([100, 56, 22]);
    expect(filas.map((f) => Math.round(f.pctImporte))).toEqual([11, 100, 0]);
    expect(filas[0].seleccionado).toBe(true);

    expect(result.current.medianas).toEqual({ count: 5, importe: 100 });
    const puntos = result.current.puntos;
    expect(puntos.find((p) => p.organo === "Ayuntamiento de Móstoles")).toMatchObject({
      medio: 100 / 9,
      seleccionado: true,
    });
    // Con tres órganos, los tres destacan y llevan nombre; y el tamaño no
    // inventa un importe medio donde no hay licitaciones.
    expect(puntos.every((p) => p.etiqueta !== "")).toBe(true);
    expect(puntos.find((p) => p.organo === "Consorci Sanitari")?.medio).toBe(0);
  });
});
