/**
 * Los hooks a los que bajaron las peticiones de las tarjetas de Ops (DLQ,
 * colas de revisión, feature flags): qué piden, qué avisan y qué refrescan.
 * Antes vivían dentro de cada tarjeta y solo se probaban montándola.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { adminKeys, analyticsKeys, featureFlagKeys } from "@/lib/query-keys";

const { apiGet, apiMutate, toast } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiMutate: vi.fn(),
  toast: { success: vi.fn(), info: vi.fn() },
}));
vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  apiGet,
  apiMutate,
}));
vi.mock("@/lib/toast", () => ({ toast }));

import { useDlq, useReencolarDlq } from "../use-dlq";
import { useGuardarFeatureFlags } from "../use-feature-flags";
import { useResolverDuplicado } from "../use-revision";

function montar<T>(hook: () => T) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const invalidar = vi.spyOn(client, "invalidateQueries");
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const clavesInvalidadas = () => invalidar.mock.calls.map(([filtro]) => filtro?.queryKey);
  return { client, clavesInvalidadas, ...renderHook(hook, { wrapper }) };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("useDlq", () => {
  it("pide el estado elegido con su tope", async () => {
    apiGet.mockResolvedValue({ items: [], resumen: [], resumen_errores: [] });
    const { result } = montar(() => useDlq("agotadas"));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiGet).toHaveBeenCalledWith("/api/v1/admin/dlq", { params: { query: { estado: "agotadas", limit: 50 } } });
  });
});

describe("useReencolarDlq", () => {
  it("si no reencoló avisa en informativo, y refresca la cola y la calidad", async () => {
    apiMutate.mockResolvedValue({ reencolada: false, detalle: "Ya no estaba en la cola" });
    const { result, clavesInvalidadas } = montar(() => useReencolarDlq());
    await act(() => result.current.mutateAsync(7));
    expect(apiMutate).toHaveBeenCalledWith("POST", "/api/v1/admin/dlq/7/reintentar");
    expect(toast.info).toHaveBeenCalledWith("Ya no estaba en la cola");
    expect(toast.success).not.toHaveBeenCalled();
    expect(clavesInvalidadas()).toEqual([adminKeys.dlq.all, analyticsKeys.quality]);
  });
});

describe("useResolverDuplicado", () => {
  it("manda la decisión como `aceptar` y, si falla, refresca la cola (otra persona ya decidió)", async () => {
    apiMutate.mockRejectedValue(new Error("404"));
    const { result, clavesInvalidadas } = montar(() => useResolverDuplicado());
    await act(async () => {
      await result.current.mutateAsync({ id: "placsp:1/2", aceptar: true }).catch(() => undefined);
    });
    expect(apiMutate).toHaveBeenCalledWith("POST", "/api/v1/admin/revision/duplicados/placsp%3A1%2F2/resolver", {
      aceptar: true,
    });
    expect(clavesInvalidadas()).toEqual([adminKeys.revision.duplicados]);
    expect(toast.success).not.toHaveBeenCalled();
  });
});

describe("useGuardarFeatureFlags", () => {
  it("lo guardado pasa a la caché antes de la relectura", async () => {
    apiMutate.mockResolvedValue(undefined);
    const { result, client } = montar(() => useGuardarFeatureFlags());
    client.setQueryData(featureFlagKeys.list, [
      { flag: "a", enabled: false, rollout_pct: 0, description: null, updated_at: null },
      { flag: "b", enabled: true, rollout_pct: 100, description: null, updated_at: null },
    ]);
    await act(() => result.current.mutateAsync([{ flag: "a", enabled: true, rollout_pct: 40 }]));
    expect(apiMutate).toHaveBeenCalledWith("PUT", "/api/v1/feature-flags", {
      flags: [{ flag: "a", enabled: true, rollout_pct: 40 }],
    });
    expect(client.getQueryData(featureFlagKeys.list)).toEqual([
      { flag: "a", enabled: true, rollout_pct: 40, description: null, updated_at: null },
      { flag: "b", enabled: true, rollout_pct: 100, description: null, updated_at: null },
    ]);
    expect(toast.success).toHaveBeenCalledWith("Cambios guardados");
  });
});
