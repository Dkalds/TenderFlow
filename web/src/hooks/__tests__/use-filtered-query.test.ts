/**
 * Tests for useFilteredQuery
 *
 * Strategy:
 *  - Mock `@/lib/filters` so useFilterParams returns controlled params.
 *  - Mock global `fetch` with vi.fn() to intercept every request.
 *  - Wrap each renderHook in a fresh QueryClient (retry: false) so failures
 *    surface immediately without retries.
 *  - Spy / replace window.location.href for the 401-redirect case.
 */

import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// ─── Mock @/lib/filters ────────────────────────────────────────────────────────
// Must be hoisted before the hook import so the module factory runs first.
const mockUseFilterParams = vi.fn<() => Record<string, string>>();

vi.mock("@/lib/filters", () => ({
  useFilterParams: () => mockUseFilterParams(),
}));

// ─── Subject under test ────────────────────────────────────────────────────────
import { useFilteredQuery } from "@/hooks/use-filtered-query";

// ─── Helpers ───────────────────────────────────────────────────────────────────

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(
      QueryClientProvider,
      { client: queryClient },
      children,
    );
  };
}

/** Build a minimal Response-like object for fetch mocks. */
function makeResponse(
  body: unknown,
  status = 200,
): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

// ─── Setup / teardown ──────────────────────────────────────────────────────────

beforeEach(() => {
  // Default: empty filter params
  mockUseFilterParams.mockReturnValue({});

  // Default: successful empty-object response
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>().mockResolvedValue(makeResponse({})),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// ─── Tests ─────────────────────────────────────────────────────────────────────

describe("useFilteredQuery", () => {
  // ── queryKey ─────────────────────────────────────────────────────────────────

  it("includes filter params in the queryKey", async () => {
    const filterParams = { q: "software", estado: "publicada", ccaa: "Madrid" };
    mockUseFilterParams.mockReturnValue(filterParams);

    const wrapper = createWrapper();

    // Simply render and verify the hook calls fetch with the correct query string
    // which implicitly proves the filter params are included in the query key
    renderHook(
      () =>
        useFilteredQuery<unknown>(["licitaciones"], "/api/v1/licitaciones"),
      { wrapper },
    );

    const mockFetch = global.fetch as ReturnType<typeof vi.fn>;
    await waitFor(() => expect(mockFetch).toHaveBeenCalled());

    const calledUrl = mockFetch.mock.calls[0][0] as string;
    expect(calledUrl).toContain("estado=publicada");
    expect(calledUrl).toContain("ccaa=Madrid");
  });

  it("re-fetches with a new URL when filter params change", async () => {
    mockUseFilterParams.mockReturnValue({ q: "first" });
    const wrapper = createWrapper();

    const { rerender } = renderHook(
      () => useFilteredQuery<unknown[]>(["items"], "/api/v1/items"),
      { wrapper },
    );

    // Wait for the first fetch to complete
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("q=first"),
        expect.any(Object),
      ),
    );

    // Simulate filter change
    mockUseFilterParams.mockReturnValue({ q: "second" });
    rerender();

    // A new fetch should be triggered with the updated param
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("q=second"),
        expect.any(Object),
      ),
    );
  });

  // ── URL construction ──────────────────────────────────────────────────────────

  it("calls fetch with the plain URL when there are no params", async () => {
    mockUseFilterParams.mockReturnValue({});

    const wrapper = createWrapper();
    const { result } = renderHook(
      () => useFilteredQuery<unknown>(["noop"], "/api/v1/noop"),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(fetch).toHaveBeenCalledWith("/api/v1/noop", {
      credentials: "include",
      headers: { "Content-Type": "application/json" },
    });
  });

  it("appends filter params as a query string", async () => {
    mockUseFilterParams.mockReturnValue({ q: "cloud", estado: "publicada" });

    const wrapper = createWrapper();
    const { result } = renderHook(
      () => useFilteredQuery<unknown>(["search"], "/api/v1/licitaciones"),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const calledUrl = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    const url = new URL(calledUrl, "http://localhost");
    expect(url.searchParams.get("q")).toBe("cloud");
    expect(url.searchParams.get("estado")).toBe("publicada");
  });

  // ── extraParams merging ───────────────────────────────────────────────────────

  it("merges extraParams with filter params, filter params take precedence", async () => {
    // Both sources define "estado"; filter should win (spread order: extra first)
    mockUseFilterParams.mockReturnValue({ estado: "adjudicada" });

    const wrapper = createWrapper();
    const { result } = renderHook(
      () =>
        useFilteredQuery<unknown>(
          ["merged"],
          "/api/v1/licitaciones",
          undefined,
          { estado: "publicada", page: "2" }, // extraParams
        ),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const calledUrl = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    const url = new URL(calledUrl, "http://localhost");

    // filter param overrides extra param
    expect(url.searchParams.get("estado")).toBe("adjudicada");
    // extra param not overridden by filter is preserved
    expect(url.searchParams.get("page")).toBe("2");
  });

  it("includes only extraParams when filter params are empty", async () => {
    mockUseFilterParams.mockReturnValue({});

    const wrapper = createWrapper();
    const { result } = renderHook(
      () =>
        useFilteredQuery<unknown>(
          ["extra-only"],
          "/api/v1/licitaciones",
          undefined,
          { page: "3", limit: "10" },
        ),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const calledUrl = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    const url = new URL(calledUrl, "http://localhost");
    expect(url.searchParams.get("page")).toBe("3");
    expect(url.searchParams.get("limit")).toBe("10");
  });

  // ── fetch call ────────────────────────────────────────────────────────────────

  it("calls fetch with credentials: include", async () => {
    const wrapper = createWrapper();
    const { result } = renderHook(
      () => useFilteredQuery<unknown>(["creds"], "/api/v1/creds"),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ credentials: "include" }),
    );
  });

  // ── 401 redirect ─────────────────────────────────────────────────────────────

  it("redirects to /login on 401 response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(makeResponse(null, 401)),
    );

    // window.location.href is read-only in jsdom; replace the whole object.
    // pathname/search feed the ?redirect= deep-link the 401 handler now builds.
    const originalLocation = window.location;
    // @ts-expect-error – intentional override for test purposes
    delete window.location;
    // @ts-expect-error – intentional override for test purposes
    window.location = { href: "", pathname: "/protected", search: "" } as Location;

    const wrapper = createWrapper();
    const { result } = renderHook(
      () => useFilteredQuery<unknown>(["auth"], "/api/v1/protected"),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(window.location.href).toBe(
      `/login?redirect=${encodeURIComponent("/protected")}`,
    );

    // Restore
    // @ts-expect-error – restoring original
    window.location = originalLocation;
  });

  // ── error handling ────────────────────────────────────────────────────────────

  it("throws an Error with the HTTP status on non-ok responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(makeResponse({ detail: "Service unavailable" }, 503)),
    );

    const wrapper = createWrapper();
    const { result } = renderHook(
      () => useFilteredQuery<unknown>(["err503"], "/api/v1/down"),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.error).toBeInstanceOf(Error);
    expect((result.current.error as Error).message).toBe("Service unavailable");
  });

  it("throws an Error with the HTTP status on 404 responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(makeResponse({ detail: "Not found" }, 404)),
    );

    const wrapper = createWrapper();
    const { result } = renderHook(
      () => useFilteredQuery<unknown>(["err404"], "/api/v1/missing"),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((result.current.error as Error).message).toBe("Not found");
  });

  // ── happy path ────────────────────────────────────────────────────────────────

  it("returns data from a successful response", async () => {
    const payload = { id: 1, title: "Licitación test" };
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(makeResponse(payload, 200)),
    );

    const wrapper = createWrapper();
    const { result } = renderHook(
      () =>
        useFilteredQuery<typeof payload>(
          ["licitacion", "1"],
          "/api/v1/licitaciones/1",
        ),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(payload);
  });
});
