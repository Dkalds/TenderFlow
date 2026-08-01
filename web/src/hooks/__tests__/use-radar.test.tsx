import * as React from "react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { useRadar } from "@/hooks/use-radar";

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useRadar", () => {
  it("sorts by fecha_publicacion ascending prefix, never the inverted '-' form", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useRadar(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain("sort=fecha_publicacion");
    expect(url).not.toContain("sort=-fecha_publicacion");
  });

  it("omits the tecnologia param when null (no filter applied)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useRadar(null), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).not.toContain("tecnologia=");
  });

  it("includes the tecnologia param when a single value is selected", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useRadar("IA"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain("tecnologia=IA");
  });

  it("uses a distinct query key per tecnologia so switching the filter refetches", () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const localWrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { rerender } = renderHook(({ tecnologia }: { tecnologia: string | null }) => useRadar(tecnologia), {
      wrapper: localWrapper,
      initialProps: { tecnologia: null },
    });
    rerender({ tecnologia: "Cloud" });

    // Distintas claves de query -> dos fetch distintos (uno por cada tecnologia).
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});
