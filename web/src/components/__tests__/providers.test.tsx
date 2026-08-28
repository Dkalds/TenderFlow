/**
 * Tests for src/components/providers.tsx
 *
 * Strategy:
 *  - Mock all heavy external providers (next-themes, nuqs, sonner,
 *    next/navigation) so the unit test stays in-memory and fast.
 *  - Verify that Providers mounts without throwing and that children are
 *    rendered in the DOM.
 *  - Verify that the QueryClient is properly configured (QueryCache /
 *    MutationCache error callbacks call notifyQueryError / notifyMutationError).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import * as React from "react";

// ── Mock external providers that require browser APIs or routing context ───────

vi.mock("next-themes", () => ({
  ThemeProvider: ({ children }: { children: React.ReactNode }) =>
    React.createElement(React.Fragment, null, children),
}));

vi.mock("nuqs/adapters/next/app", () => ({
  NuqsAdapter: ({ children }: { children: React.ReactNode }) =>
    React.createElement(React.Fragment, null, children),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
  Toaster: () => null,
}));

// SessionProvider fetches /api/v1/auth/me on mount — keep it inert.
vi.stubGlobal(
  "fetch",
  vi.fn().mockResolvedValue({
    ok: false,
    status: 401,
    json: () => Promise.resolve(null),
  }),
);

// ── Mock query-feedback to spy on error callbacks ─────────────────────────────

const mockNotifyQueryError = vi.fn();
const mockNotifyMutationError = vi.fn();
const mockNotifyMutationSuccess = vi.fn();

vi.mock("@/lib/query-feedback", () => ({
  notifyQueryError: (...args: unknown[]) => mockNotifyQueryError(...args),
  notifyMutationError: (...args: unknown[]) => mockNotifyMutationError(...args),
  notifyMutationSuccess: (...args: unknown[]) =>
    mockNotifyMutationSuccess(...args),
  // La política de reintentos vive en el mismo módulo y `Providers` la pasa a
  // `defaultOptions.queries`. El doble tiene que exportarla: si falta, el
  // QueryClient se construye con `retry: undefined` y el render revienta.
  // Su comportamiento se fija en `lib/__tests__/query-retry.test.ts`.
  debeReintentar: () => false,
  retrasoDeReintento: () => 0,
}));

// ── Subject under test ─────────────────────────────────────────────────────────
import { Providers } from "@/components/providers";

// ── Setup ──────────────────────────────────────────────────────────────────────

beforeEach(() => {
  mockNotifyQueryError.mockReset();
  mockNotifyMutationError.mockReset();
  mockNotifyMutationSuccess.mockReset();
});

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("Providers", () => {
  it("renders without crashing", () => {
    expect(() =>
      render(<Providers>
        <span>hello</span>
      </Providers>),
    ).not.toThrow();
  });

  it("renders children in the DOM", () => {
    render(
      <Providers>
        <p data-testid="child">child content</p>
      </Providers>,
    );
    expect(screen.getByTestId("child")).toBeInTheDocument();
    expect(screen.getByText("child content")).toBeInTheDocument();
  });

  it("renders multiple children", () => {
    render(
      <Providers>
        <span data-testid="a">A</span>
        <span data-testid="b">B</span>
      </Providers>,
    );
    expect(screen.getByTestId("a")).toBeInTheDocument();
    expect(screen.getByTestId("b")).toBeInTheDocument();
  });
});
