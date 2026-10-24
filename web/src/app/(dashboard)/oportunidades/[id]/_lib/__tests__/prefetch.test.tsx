import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

/**
 * Paridad del prefetch de la ficha de la oportunidad con su hook: el listado
 * de organizaciones se cachea bajo la clave que hidrata el servidor, desde la
 * misma ruta y con la misma forma (el `select` del hook no toca la caché).
 */

import { useOrganizations } from "@/hooks/use-organization";
import { consultasFicha } from "../prefetch";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const ORGANIZACIONES = [
  { id: 1, name: "Personal", role: "owner", is_personal: true },
  { id: 21, name: "Equipo SAP", role: "admin", is_personal: false },
];

describe("prefetch de la ficha de la oportunidad", () => {
  it("cachea bajo la clave del hook, pide la misma ruta y guarda la misma forma", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(ORGANIZACIONES)));
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    renderHook(() => useOrganizations(), { wrapper });
    await waitFor(() => expect(client.isFetching()).toBe(0));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    const pedidas = fetchMock.mock.calls.map((call) => callUrl(call));
    for (const consulta of consultasFicha()) {
      expect(pedidas).toContain(consulta.path);
      expect(client.getQueryData(consulta.queryKey)).toEqual(ORGANIZACIONES);
    }
  });

  it("no pide nada que dependa de la organización activa", () => {
    // Regla 2 de `lib/server-prefetch.ts`: ni `organization_id` en la ruta ni
    // un id de organización en la clave.
    for (const consulta of consultasFicha()) {
      expect(consulta.path).not.toContain("organization_id");
      expect(consulta.queryKey).toEqual(["organizations"]);
    }
  });
});
