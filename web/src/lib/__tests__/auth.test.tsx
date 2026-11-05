/**
 * Tests for web/src/lib/auth.tsx
 *
 * Covers: SessionProvider, useSession hook, admin detection,
 *         session refresh, unauthenticated state.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionProvider, useSession } from "@/lib/auth";
import { respuestaDeContrato } from "@/test/contrato";

const YO = respuestaDeContrato("/api/v1/auth/me");

function createWrapper(retry: boolean | number = false) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry, retryDelay: 0, gcTime: 0 },
    },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <SessionProvider>{children}</SessionProvider>
      </QueryClientProvider>
    );
  };
}

function mockFetchMe(status: number, body: unknown) {
  const jsonFn = vi.fn().mockResolvedValue(body);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: jsonFn,
  }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("useSession", () => {
  beforeEach(() => {
    mockFetchMe(200, { ...YO, email: "admin@test.com", is_admin: true });
  });

  it("throws when used outside SessionProvider", () => {
    expect(() => renderHook(() => useSession())).toThrow(
      "useSession must be used within a SessionProvider",
    );
  });

  it("returns authenticated user data", async () => {
    const { result } = renderHook(() => useSession(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.isAdmin).toBe(true);
    expect(result.current.user?.email).toBe("admin@test.com");
  });

  it("detects non-admin users", async () => {
    mockFetchMe(200, { ...YO, user_id: 2, email: "user@test.com", is_admin: false });
    const { result } = renderHook(() => useSession(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.isAdmin).toBe(false);
  });

  it("returns isAuthenticated=false on 401", async () => {
    mockFetchMe(401, { detail: "Unauthorized" });
    const { result } = renderHook(() => useSession(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.user).toBeNull();
  });

  it("403 también es «sin sesión», sin error", async () => {
    mockFetchMe(403, { detail: "Forbidden" });
    const { result } = renderHook(() => useSession(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.user).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it("un 5xx no es «sin sesión»: queda como error, no como usuario anónimo", async () => {
    mockFetchMe(503, { detail: "Arrancando" });
    const { result } = renderHook(() => useSession(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.error).toBeInstanceOf(Error);
  });

  it("un fallo de red queda como error, no como sesión cerrada", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const { result } = renderHook(() => useSession(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.error).toBeInstanceOf(Error);
  });

  it("reintenta con la política del QueryClient y recupera la sesión tras un 5xx", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: vi.fn().mockResolvedValue({}) })
      .mockResolvedValue({ ok: true, status: 200, json: vi.fn().mockResolvedValue(YO) });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useSession(), { wrapper: createWrapper(1) });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));
    expect(result.current.user?.user_id).toBe(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("provides a refresh function", async () => {
    const { result } = renderHook(() => useSession(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(typeof result.current.refresh).toBe("function");
  });
});
