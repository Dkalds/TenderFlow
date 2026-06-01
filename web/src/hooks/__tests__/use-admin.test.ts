/**
 * Tests for useAdmin
 *
 * Strategy:
 *  - Mock global `fetch` with vi.fn() to control /api/v1/auth/me responses.
 *  - Use renderHook + waitFor from @testing-library/react.
 *  - Wrap hook in QueryClientProvider since useAdmin now uses useQuery.
 */

import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// ─── Subject under test ────────────────────────────────────────────────────────
import { useAdmin } from "@/hooks/use-admin";

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
function makeResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

// ─── Setup / teardown ──────────────────────────────────────────────────────────

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>().mockResolvedValue(makeResponse({ is_admin: false })),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// ─── Tests ─────────────────────────────────────────────────────────────────────

describe("useAdmin", () => {
  // ── Initial state ─────────────────────────────────────────────────────────────

  it("returns false initially before the fetch settles", () => {
    // Make fetch never resolve so we can observe the synchronous initial state.
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockReturnValue(new Promise(() => {})),
    );

    const { result } = renderHook(() => useAdmin(), { wrapper: createWrapper() });

    // Synchronous snapshot — must be false before any async work finishes.
    expect(result.current).toBe(false);
  });

  // ── is_admin flag ─────────────────────────────────────────────────────────────

  it("returns true when the API reports is_admin: true", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        makeResponse({ is_admin: true, role: "user" }),
      ),
    );

    const { result } = renderHook(() => useAdmin(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current).toBe(true));
  });

  it("returns false when the API reports is_admin: false and role is not admin", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        makeResponse({ is_admin: false, role: "viewer" }),
      ),
    );

    const { result } = renderHook(() => useAdmin(), { wrapper: createWrapper() });

    await waitFor(() =>
      // Wait for the fetch to have been called at least once
      expect(fetch).toHaveBeenCalled(),
    );
    // Give micro-tasks time to flush
    await act(async () => {});
    expect(result.current).toBe(false);
  });

  // ── role field ────────────────────────────────────────────────────────────────

  it('returns true when the API reports role: "admin" (is_admin absent)', async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        makeResponse({ role: "admin" }),
      ),
    );

    const { result } = renderHook(() => useAdmin(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current).toBe(true));
  });

  it('returns false when role is "user" and is_admin is false', async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        makeResponse({ is_admin: false, role: "user" }),
      ),
    );

    const { result } = renderHook(() => useAdmin(), { wrapper: createWrapper() });

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    await act(async () => {});
    expect(result.current).toBe(false);
  });

  // ── error paths ───────────────────────────────────────────────────────────────

  it("returns false when fetch rejects (network error)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockRejectedValue(new Error("Network failure")),
    );

    const { result } = renderHook(() => useAdmin(), { wrapper: createWrapper() });

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    await act(async () => {});
    expect(result.current).toBe(false);
  });

  it("returns false when the response is not ok (e.g. 403)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(makeResponse(null, 403)),
    );

    const { result } = renderHook(() => useAdmin(), { wrapper: createWrapper() });

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    await act(async () => {});
    expect(result.current).toBe(false);
  });

  it("returns false when the response is 401 Unauthorized", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(makeResponse(null, 401)),
    );

    const { result } = renderHook(() => useAdmin(), { wrapper: createWrapper() });

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    await act(async () => {});
    expect(result.current).toBe(false);
  });

  // ── fetch call ────────────────────────────────────────────────────────────────

  it("calls /api/v1/auth/me with credentials: include", async () => {
    const { result } = renderHook(() => useAdmin(), { wrapper: createWrapper() });

    await waitFor(() => expect(fetch).toHaveBeenCalled());

    expect(fetch).toHaveBeenCalledWith("/api/v1/auth/me", {
      credentials: "include",
    });

    // Suppress "act" warning — ensure all state updates flush
    await act(async () => {});
    expect(result.current).toBe(false);
  });

  // ── cancellation ─────────────────────────────────────────────────────────────

  it("does not cause errors when unmounted before fetch settles", async () => {
    /**
     * With the React Query-based implementation, lifecycle management
     * (cancellation, cleanup) is handled by React Query internally.
     * This test verifies that unmounting early does not throw or warn.
     */
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockReturnValue(new Promise(() => {})),
    );

    const { result, unmount } = renderHook(() => useAdmin(), { wrapper: createWrapper() });

    // Unmount before the fetch has resolved
    unmount();

    // Should still be the initial false — no state update after unmount
    expect(result.current).toBe(false);
  });
});
