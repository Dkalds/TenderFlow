/**
 * `useLicitacionesConPursuit` pide `/pursuits` al tope de página y sigue por
 * `offset` hasta `total`: renovaciones marcaba solo las oportunidades de la
 * primera página (50) y dejaba sin marca el resto.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, renderHook, waitFor } from "@testing-library/react";

const apiGet = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  apiGet,
}));
vi.mock("@/hooks/use-organization", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/use-organization")>()),
  useActiveOrganizationId: () => 7,
}));

import { useLicitacionesConPursuit } from "@/hooks/use-pursuits";

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const pagina = (ids: string[], total: number) => ({
  organization_id: 7,
  items: ids.map((licitacion_id) => ({ licitacion_id })),
  total,
  limit: 500,
  offset: 0,
});

afterEach(() => {
  cleanup();
  apiGet.mockReset();
});

describe("useLicitacionesConPursuit", () => {
  it("junta todas las páginas en un Set de licitacion_id", async () => {
    apiGet.mockResolvedValueOnce(pagina(["A", "B"], 3)).mockResolvedValueOnce(pagina(["C"], 3));

    const { result } = renderHook(() => useLicitacionesConPursuit(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(new Set(["A", "B", "C"]));
    expect(apiGet).toHaveBeenCalledTimes(2);
    const consultas = apiGet.mock.calls.map(([ruta, opciones]) => [ruta, opciones.params.query]);
    expect(consultas).toEqual([
      ["/api/v1/pursuits", { organization_id: 7, limit: 500, offset: 0 }],
      ["/api/v1/pursuits", { organization_id: 7, limit: 500, offset: 2 }],
    ]);
  });

  it("una página vacía corta aunque total diga más", async () => {
    apiGet.mockResolvedValueOnce(pagina(["A"], 10)).mockResolvedValueOnce(pagina([], 10));

    const { result } = renderHook(() => useLicitacionesConPursuit(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(new Set(["A"]));
    expect(apiGet).toHaveBeenCalledTimes(2);
  });
});
