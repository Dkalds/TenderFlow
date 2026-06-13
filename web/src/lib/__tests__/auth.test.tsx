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

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
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
    mockFetchMe(200, {
      user_id: "u1",
      email: "admin@test.com",
      display_name: "Admin",
      is_admin: true,
      role: "admin",
    });
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
    mockFetchMe(200, {
      user_id: "u2",
      email: "user@test.com",
      display_name: "User",
      is_admin: false,
    });
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

  it("returns isAuthenticated=false on network error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Network error")));
    const { result } = renderHook(() => useSession(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.user).toBeNull();
  });

  it("provides a refresh function", async () => {
    const { result } = renderHook(() => useSession(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(typeof result.current.refresh).toBe("function");
  });
});
