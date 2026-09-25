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
  ThemeProvider: ({ children }: { children: React.ReactNode }) => React.createElement(React.Fragment, null, children),
}));

vi.mock("nuqs/adapters/next/app", () => ({
  NuqsAdapter: ({ children }: { children: React.ReactNode }) => React.createElement(React.Fragment, null, children),
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
  notifyMutationSuccess: (...args: unknown[]) => mockNotifyMutationSuccess(...args),
  // La política de reintentos vive en el mismo módulo y `Providers` la pasa a
  // `defaultOptions.queries`. El doble tiene que exportarla: si falta, el
  // QueryClient se construye con `retry: undefined` y el render revienta.
  // Su comportamiento se fija en `lib/__tests__/query-retry.test.ts`.
  debeReintentar: () => false,
  retrasoDeReintento: () => 0,
}));

// ── Subject under test ─────────────────────────────────────────────────────────
import { QueryObserver } from "@tanstack/react-query";
import { crearQueryClient, Providers } from "@/components/providers";
import { analyticsKeys, pursuitKeys } from "@/lib/query-keys";

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
      render(
        <Providers>
          <span>hello</span>
        </Providers>,
      ),
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

describe("crearQueryClient — la política común de consultas", () => {
  it("conserva la caché 30 minutos; lo fresco lo sigue decidiendo `staleTime`", () => {
    // Con los 5 min de React Query, volver a una pantalla tras cinco minutos
    // volvía a pintar esqueletos y a relanzar sus agregados.
    const queries = crearQueryClient().getDefaultOptions().queries;
    expect(queries?.gcTime).toBe(30 * 60 * 1000);
    expect(queries?.staleTime).toBe(5 * 60 * 1000);
  });

  it("al volver a la pestaña sólo se refresca lo que otros cambian entretanto", () => {
    const client = crearQueryClient();
    const alVolver = (queryKey: readonly unknown[]) => client.defaultQueryOptions({ queryKey }).refetchOnWindowFocus;

    // Los agregados de mercado cambian a diario: volver a la pestaña no los
    // relanza contra una API de un solo proceso.
    expect(alVolver(analyticsKeys.overview({ ccaa: "MD" }))).toBe(false);
    expect(alVolver(["radar", "scoring", 7, null])).toBe(false);
    expect(alVolver([...pursuitKeys.metrics, 7])).toBe(false);

    // Lo que mueve el equipo, o avisa, sí.
    expect(alVolver([...pursuitKeys.agenda, { soloMios: false, tecnologia: null, ccaa: null }, 7])).toBe(true);
    expect(alVolver(["notifications"])).toBe(true);
    expect(alVolver([...pursuitKeys.list({}), 7])).toBe(true);
    expect(alVolver([...pursuitKeys.detail("10"), 7])).toBe(true);
    expect(alVolver([...pursuitKeys.tasks("10"), 7])).toBe(true);
  });

  it("una consulta cancelada no llega al aviso de error", async () => {
    // Es lo que pasa con la petición del filtro anterior: la consulta se queda
    // sin observadores y React Query aborta su `signal`.
    const client = crearQueryClient();
    const observer = new QueryObserver(client, {
      queryKey: ["cancelable"],
      queryFn: ({ signal }) =>
        new Promise((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(new DOMException("The operation was aborted.", "AbortError")));
        }),
    });
    const dejarDeObservar = observer.subscribe(() => {});
    dejarDeObservar();
    await new Promise((resolve) => setTimeout(resolve, 10));

    expect(mockNotifyQueryError).not.toHaveBeenCalled();
    expect(client.getQueryState(["cancelable"])?.status).toBe("pending");
    expect(client.getQueryState(["cancelable"])?.fetchStatus).toBe("idle");
  });
});
