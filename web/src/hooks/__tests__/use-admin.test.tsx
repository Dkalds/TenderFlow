/**
 * Tests for web/src/hooks/use-admin.ts
 *
 * Covers: admin detection via SessionContext, non-admin state.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionProvider } from "@/lib/auth";
import { useAdmin } from "@/hooks/use-admin";

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

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("useAdmin", () => {
  it("returns true when user has is_admin flag", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({
        user_id: 1,
        email: "admin@test.com",
        is_admin: true,
      }),
    }));
    const { result } = renderHook(() => useAdmin(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current).toBe(true));
  });

  // `/auth/me` no manda `role` (`UserInfo`): solo cuenta `is_admin`.
  it("un `role` que la API no manda no da permisos de administrador", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({
        user_id: 1,
        email: "admin@test.com",
        is_admin: false,
        role: "admin",
      }),
    }));
    const { result } = renderHook(() => useAdmin(), { wrapper: createWrapper() });
    await new Promise((r) => setTimeout(r, 0));
    await waitFor(() => expect(result.current).toBe(false));
  });

  it("returns false for regular users", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({
        user_id: 2,
        email: "user@test.com",
        is_admin: false,
      }),
    }));
    const { result } = renderHook(() => useAdmin(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current).toBe(false));
  });

  it("returns false on auth failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: vi.fn().mockResolvedValue({ detail: "Unauthorized" }),
    }));
    const { result } = renderHook(() => useAdmin(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current).toBe(false));
  });
});
