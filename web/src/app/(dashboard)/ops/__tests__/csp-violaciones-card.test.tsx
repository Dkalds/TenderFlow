import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

/**
 * Bloqueos de la política CSP en Ops › Estado: la tabla `csp_violations` se
 * llenaba desde 2026-06 y ninguna pantalla la leía.
 */

import { CspViolacionesCard } from "../_components/observabilidad/csp-violaciones-card";

const AGRUPADAS = {
  dias: 30,
  items: [
    {
      directiva: "frame-src",
      origen: "https://www.youtube.com",
      veces: 14,
      primera_vez: "2026-11-01T10:00:00+00:00",
      ultima_vez: "2026-11-08T09:30:00+00:00",
      documento_ejemplo: "https://app.example.test/licitaciones/abc",
    },
  ],
};

function montar(cuerpo: unknown, status = 200) {
  const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(cuerpo, status)));
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <CspViolacionesCard />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("CspViolacionesCard", () => {
  it("lista directiva, origen y veces de cada grupo", async () => {
    const fetchMock = montar(AGRUPADAS);

    expect(await screen.findByText("frame-src")).toBeInTheDocument();
    expect(screen.getByText("https://www.youtube.com")).toBeInTheDocument();
    expect(screen.getByText("14")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some((c) => callUrl(c).includes("/security/csp-violations"))).toBe(true);
  });

  it("sin bloqueos lo dice en vez de enseñar una tabla vacía", async () => {
    montar({ dias: 30, items: [] });

    expect(await screen.findByText("Ningún bloqueo registrado")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("si la API falla lo dice en el panel", async () => {
    montar({ detail: "boom" }, 500);

    expect(
      await screen.findByText("No se pudieron cargar los bloqueos de la política CSP"),
    ).toBeInTheDocument();
  });
});
