import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

/**
 * Paridad del prefetch del Radar con sus hooks: misma clave, misma ruta y el
 * mismo valor cacheado (los descartes se cachean como `ids`, no como la
 * respuesta entera). Si divergen, el servidor paga la petición y el cliente la
 * repite — o peor, el hook lee una forma que no espera.
 */

import { useRadarDismissals } from "@/hooks/use-radar";
import { useRadarProximas } from "../../_hooks/use-radar-proximas";
import { consultasRadar } from "../prefetch";

vi.mock("@/hooks/use-organization", () => ({ useActiveOrganizationId: () => null }));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const CUERPOS: Record<string, unknown> = {
  "/api/v1/radar/dismissals": { ids: ["A-1", "B-2"] },
  "/api/v1/radar/proximas": { items: [], total: 0, con_fecha_prevista: 0, estados: ["PRE", "CPM"] },
};

function cuerpoDe(url: string): unknown {
  return CUERPOS[url.split("?")[0]];
}

describe("prefetch del Radar", () => {
  it("cachea bajo la clave de los hooks, pide la misma ruta y guarda la misma forma", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((...call: unknown[]) => Promise.resolve(jsonResponse(cuerpoDe(callUrl(call)))));
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    renderHook(() => [useRadarDismissals(), useRadarProximas()], { wrapper });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(client.isFetching()).toBe(0));

    const pedidas = fetchMock.mock.calls.map((call) => callUrl(call));
    for (const consulta of consultasRadar()) {
      expect(pedidas).toContain(consulta.path);
      const cuerpo = cuerpoDe(consulta.path);
      const esperado = consulta.transformar ? consulta.transformar(cuerpo) : cuerpo;
      expect(client.getQueryData(consulta.queryKey)).toEqual(esperado);
    }
  });
});
