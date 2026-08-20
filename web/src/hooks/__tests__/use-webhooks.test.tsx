import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useCreateWebhook, usePingWebhook, useWebhookEventTypes, useWebhooks } from "@/hooks/use-webhooks";
import { callUrl, jsonResponse } from "./fetch-call";

const toastCalls: Array<[string, string]> = [];
vi.mock("sonner", () => ({
  toast: {
    success: (m: string) => toastCalls.push(["success", m]),
    warning: (m: string) => toastCalls.push(["warning", m]),
    error: (m: string) => toastCalls.push(["error", m]),
  },
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function stub(body: unknown) {
  const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(body)));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  toastCalls.length = 0;
});

describe("useWebhooks", () => {
  it("lista los webhooks del usuario", async () => {
    stub([{ id: 1, name: "slack", url: "https://x.test", event_types: ["*"], active: true }]);

    const { result } = renderHook(() => useWebhooks(), { wrapper });
    await waitFor(() => expect(result.current.data).toHaveLength(1));

    expect(result.current.data![0].name).toBe("slack");
  });

  it("toma los tipos de evento del backend, no de una lista local", async () => {
    // Duplicar la lista en el cliente la dejaría divergir del validador que
    // rechaza el alta.
    const fetchMock = stub({ event_types: ["*", "watchlist_match"] });

    const { result } = renderHook(() => useWebhookEventTypes(), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual(["*", "watchlist_match"]));

    expect(callUrl(fetchMock.mock.calls[0])).toBe("/api/v1/webhooks/event-types");
  });

  it("el alta devuelve el secret, que solo viaja esta vez", async () => {
    stub({
      id: 7,
      name: "n",
      url: "https://x.test",
      event_types: ["*"],
      secret: "shhh", // pragma: allowlist secret (literal de stub)
    });

    const { result } = renderHook(() => useCreateWebhook(), { wrapper });
    let created: { secret?: string } | undefined;
    await act(async () => {
      created = await result.current.mutateAsync({
        name: "n",
        url: "https://x.test",
        event_types: ["*"],
      });
    });

    expect(created?.secret).toBe("shhh");
  });
});

describe("ping de prueba", () => {
  it("una entrega correcta se confirma", async () => {
    stub({ success: true, status_code: 200, attempts: 1 });

    const { result } = renderHook(() => usePingWebhook(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync(1);
    });

    expect(toastCalls).toContainEqual(["success", "Entrega correcta (HTTP 200)"]);
  });

  it("una entrega fallida informa del motivo en vez de decir solo 'error'", async () => {
    // El ping existe justamente para diagnosticar: el motivo es el dato útil.
    stub({ success: false, error: "connection refused", attempts: 3 });

    const { result } = renderHook(() => usePingWebhook(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync(1);
    });

    const [level, message] = toastCalls.at(-1)!;
    expect(level).toBe("warning");
    expect(message).toContain("connection refused");
    expect(message).toContain("3 intento");
  });
});
