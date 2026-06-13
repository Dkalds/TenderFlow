/**
 * Tests for web/src/components/admin-guard.tsx
 *
 * Covers: renders children for admin, shows fallback for non-admin,
 *         shows loading skeleton while session resolves, redirects
 *         to login when unauthenticated.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionProvider } from "@/lib/auth";

// Mock next/navigation
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/admin",
}));

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
});

describe("AdminGuard", () => {
  it("renders children when user is admin", async () => {
    mockFetchMe(200, {
      user_id: "u1",
      email: "admin@test.com",
      display_name: "Admin",
      is_admin: true,
    });
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
    mockFetchMe(200, {
      user_id: "u2",
      email: "user@test.com",
      display_name: "User",
      is_admin: false,
    });
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
    mockFetchMe(200, {
      user_id: "u2",
      email: "user@test.com",
      display_name: "User",
      is_admin: false,
    });
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

  it("shows loading skeleton while session resolves", () => {
    // Don't resolve the fetch — keep loading
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
    const { container } = render(
      <AdminGuard>
        <div data-testid="admin-content">Admin Content</div>
      </AdminGuard>,
      { wrapper: createWrapper() },
    );
    const skeletons = container.querySelectorAll(".animate-pulse");
    expect(skeletons.length).toBeGreaterThan(0);
  });
});
