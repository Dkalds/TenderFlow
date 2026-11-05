/**
 * Tests for web/src/components/admin-guard.tsx
 *
 * Covers: renders children for admin, shows fallback for non-admin,
 *         shows loading skeleton while session resolves, redirects
 *         to login when unauthenticated, and does not when `/auth/me` failed.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionProvider } from "@/lib/auth";
import { respuestaDeContrato } from "@/test/contrato";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/admin",
}));

const YO = respuestaDeContrato("/api/v1/auth/me");

import { AdminGuard } from "@/components/admin-guard";

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
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
  }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  push.mockReset();
});

describe("AdminGuard", () => {
  it("renders children when user is admin", async () => {
    mockFetchMe(200, { ...YO, is_admin: true });
    render(
      <AdminGuard>
        <div data-testid="admin-content">Admin Content</div>
      </AdminGuard>,
      { wrapper: createWrapper() },
    );
    const content = await screen.findByTestId("admin-content");
    expect(content).toBeDefined();
    expect(content.textContent).toBe("Admin Content");
  });

  it("shows access restricted when user is not admin", async () => {
    mockFetchMe(200, { ...YO, user_id: 2, is_admin: false });
    render(
      <AdminGuard>
        <div data-testid="admin-content">Admin Content</div>
      </AdminGuard>,
      { wrapper: createWrapper() },
    );
    const restricted = await screen.findByText("Acceso restringido");
    expect(restricted).toBeDefined();
    expect(screen.queryByTestId("admin-content")).toBeNull();
  });

  it("renders custom fallback when user is not admin", async () => {
    mockFetchMe(200, { ...YO, user_id: 2, is_admin: false });
    render(
      <AdminGuard fallback={<div data-testid="custom-fallback">No access</div>}>
        <div data-testid="admin-content">Admin Content</div>
      </AdminGuard>,
      { wrapper: createWrapper() },
    );
    const fallback = await screen.findByTestId("custom-fallback");
    expect(fallback).toBeDefined();
    expect(fallback.textContent).toBe("No access");
  });

  it("sin sesión (401) manda a /login", async () => {
    mockFetchMe(401, { detail: "Unauthorized" });
    render(
      <AdminGuard>
        <div>Admin Content</div>
      </AdminGuard>,
      { wrapper: createWrapper() },
    );
    await waitFor(() => expect(push).toHaveBeenCalledWith("/login"));
  });

  it("si /auth/me falla (5xx) pinta el error con Reintentar y no manda a /login", async () => {
    mockFetchMe(503, { detail: "Arrancando" });
    render(
      <AdminGuard>
        <div data-testid="admin-content">Admin Content</div>
      </AdminGuard>,
      { wrapper: createWrapper() },
    );
    expect(await screen.findByText("No se pudo comprobar tu sesión")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reintentar/i })).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
    expect(screen.queryByTestId("admin-content")).toBeNull();
  });

  it("shows loading skeleton while session resolves", () => {
    // Don't resolve the fetch — keep loading
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
    const { container } = render(
      <AdminGuard>
        <div data-testid="admin-content">Admin Content</div>
      </AdminGuard>,
      { wrapper: createWrapper() },
    );
    // El esqueleto de la casa (`Skeleton`), no el `animate-pulse` de shadcn:
    // un solo lenguaje de carga en toda la consola.
    const skeletons = container.querySelectorAll('[data-slot="skeleton"]');
    expect(skeletons.length).toBeGreaterThan(0);
    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(0);
  });
});
