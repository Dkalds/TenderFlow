/**
 * Guardar los pesos del go/no-go (C6.4) invalida la matriz de las fichas.
 *
 * El total y la recomendación de cada oportunidad se calculan en el servidor
 * con esos pesos: si la mutación no tirase también `pursuitKeys.goNoGoTodas`,
 * la ficha que se abra después enseñaría, hasta que caduque su `staleTime`, una
 * puntuación con los pesos de antes. Una entrada ajena (la lista de
 * oportunidades) no tiene por qué invalidarse.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { callMethod, callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";
import { gobiernoOrgKeys, pursuitKeys } from "@/lib/query-keys";

import { useGuardarPesosGoNoGo } from "../use-pesos-go-no-go";

const PESOS = {
  organization_id: 7,
  umbral: 3,
  criterios: [{ criterio: "encaje", etiqueta: "Encaje estratégico", invertido: false, peso: 2 }],
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("useGuardarPesosGoNoGo", () => {
  it("invalida la matriz go/no-go de todas las oportunidades, en cualquier organización", async () => {
    const fetch = vi.fn(async () => jsonResponse(PESOS));
    vi.stubGlobal("fetch", fetch);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const claveFicha9 = [...pursuitKeys.goNoGo(9), 7];
    const claveFicha12 = [...pursuitKeys.goNoGo(12), 7];
    const claveLista = pursuitKeys.list({ estado: "abierto" });
    client.setQueryData(claveFicha9, { total: 3 });
    client.setQueryData(claveFicha12, { total: 4 });
    client.setQueryData(claveLista, []);
    client.setQueryData(gobiernoOrgKeys.pesosGoNoGo(7), PESOS);

    const { result } = renderHook(() => useGuardarPesosGoNoGo(7), {
      wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
    });
    await act(async () => {
      await result.current.mutateAsync({ encaje: 2 });
    });

    const llamada = fetch.mock.calls[0] as unknown as readonly unknown[];
    expect(callMethod(llamada)).toBe("PUT");
    expect(callUrl(llamada)).toBe("/api/v1/organizations/go-no-go/weights?organization_id=7");
    await waitFor(() => {
      expect(client.getQueryState(claveFicha9)?.isInvalidated).toBe(true);
      expect(client.getQueryState(claveFicha12)?.isInvalidated).toBe(true);
    });
    expect(client.getQueryState(claveLista)?.isInvalidated).toBe(false);
  });
});
