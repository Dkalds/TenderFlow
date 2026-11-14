/**
 * Las peticiones del dossier de un competidor, ya fuera de sus componentes:
 * la exportación de adjudicaciones por páginas, el grupo de «contra mí» y los
 * socios de UTE, que sin segmento no se piden.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, renderHook, waitFor } from "@testing-library/react";

const { apiGet, fetchWithAuth } = vi.hoisted(() => ({ apiGet: vi.fn(), fetchWithAuth: vi.fn() }));
vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  apiGet,
  fetchWithAuth,
}));
vi.mock("@/hooks/use-organization", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/use-organization")>()),
  useActiveOrganizationId: () => 3,
}));

import { todasLasAdjudicaciones, useBatallasContraMi, useSociosUte } from "@/hooks/use-empresa-competencia";

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const query = (url: string) => Object.fromEntries(new URL(url, "http://x").searchParams);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("todasLasAdjudicaciones", () => {
  it("sigue por offset con el paso que devolvió la primera página, conservando los filtros", async () => {
    fetchWithAuth.mockImplementation((url: string) => {
      const offset = Number(query(url).offset);
      // El backend recorta el limit a 2: el paso es 2, no 500.
      const items = offset < 5 ? [{ licitacion_id: `L${offset}` }, { licitacion_id: `L${offset + 1}` }] : [];
      return Promise.resolve({ items: items.slice(0, 5 - offset), total: 5 });
    });

    const filas = await todasLasAdjudicaciones(9, "q=sap&sort=fecha_desc");

    expect(filas.map((f) => f.licitacion_id)).toEqual(["L0", "L1", "L2", "L3", "L4"]);
    const pedidas: string[] = fetchWithAuth.mock.calls.map(([url]) => String(url));
    expect(pedidas.every((url) => url.startsWith("/api/v1/competitive/empresas/9/adjudicaciones?"))).toBe(true);
    expect(pedidas.map((url) => query(url))).toEqual([
      { q: "sap", sort: "fecha_desc", limit: "500", offset: "0" },
      { q: "sap", sort: "fecha_desc", limit: "500", offset: "2" },
      { q: "sap", sort: "fecha_desc", limit: "500", offset: "4" },
    ]);
  });
});

describe("useBatallasContraMi", () => {
  it("manda la organización y, con varias identidades, el grupo", async () => {
    fetchWithAuth.mockResolvedValue({ batallas: [] });
    const { result } = renderHook(() => useBatallasContraMi("12", 24, [12, 15]), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const [url] = fetchWithAuth.mock.calls[0] as [string];
    expect(url.startsWith("/api/v1/competitive/empresas/12/contra-mi?")).toBe(true);
    expect(query(url)).toEqual({ meses: "24", organization_id: "3", empresa_ids: "12,15" });
  });
});

describe("useSociosUte", () => {
  it("sin prefijo CPV no pide nada", () => {
    const { result } = renderHook(() => useSociosUte(null, "Madrid", 5), { wrapper });
    expect(result.current.fetchStatus).toBe("idle");
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("con segmento pide el CPV, la CCAA y el límite", async () => {
    apiGet.mockResolvedValue({ socios: [], lideres: [] });
    const { result } = renderHook(() => useSociosUte("7221", null, 5), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiGet).toHaveBeenCalledWith("/api/v1/competitive/partners", {
      params: { query: { cpv: "7221", ccaa: undefined, limit: 5 } },
    });
  });
});
