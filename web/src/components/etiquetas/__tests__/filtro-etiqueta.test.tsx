/**
 * F1.6 — el filtro por etiqueta que comparten Oportunidades, el Radar y
 * Detalle. Se fija que filtra lo cargado (y lo dice), que sin etiquetas no se
 * pinta, y que no pide etiquetas por objeto hasta que se usa.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import type * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

vi.mock("@/hooks/use-organization", () => ({ useActiveOrganizationId: () => 3 }));

import {
  FiltroEtiquetaSelect,
  TODAS_LAS_ETIQUETAS,
  pasaFiltroEtiqueta,
  useFiltroEtiqueta,
} from "@/components/etiquetas/filtro-etiqueta";

const Q4 = { id: 7, nombre: "Q4", color: "#2563eb" };

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function stubApi(etiquetas: unknown[], porObjeto: Record<string, unknown[]>) {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = input instanceof Request ? input.url : String(input);
    if (url.includes("/etiquetas/por-objeto")) return jsonResponse({ por_objeto: porObjeto });
    if (url.includes("/etiquetas")) return jsonResponse(etiquetas);
    return jsonResponse({ detail: "no esperada" }, 404);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("pasaFiltroEtiqueta", () => {
  it("«todas» no filtra; una etiqueta exige que el objeto la lleve", () => {
    expect(pasaFiltroEtiqueta(undefined, TODAS_LAS_ETIQUETAS)).toBe(true);
    expect(pasaFiltroEtiqueta([Q4], "7")).toBe(true);
    expect(pasaFiltroEtiqueta([Q4], "8")).toBe(false);
    expect(pasaFiltroEtiqueta(undefined, "7")).toBe(false);
  });
});

describe("useFiltroEtiqueta", () => {
  it("no pide etiquetas por objeto hasta que se filtra, y entonces filtra lo cargado", async () => {
    const fetch = stubApi([Q4], { "LIC-1": [Q4], "LIC-2": [] });
    const { result } = renderHook(() => useFiltroEtiqueta("favorito", ["LIC-1", "LIC-2"]), {
      wrapper,
    });
    expect(result.current.pasa("LIC-2")).toBe(true);
    expect(fetch.mock.calls.some((c) => callUrl(c).includes("por-objeto"))).toBe(false);

    act(() => result.current.setFiltro("7"));
    // Mientras carga, nada pasa: filtrar es excluir, no «todo hasta saber».
    expect(result.current.pasa("LIC-1")).toBe(false);
    await waitFor(() => expect(result.current.pasa("LIC-1")).toBe(true));
    expect(result.current.pasa("LIC-2")).toBe(false);
    expect(callUrl(fetch.mock.calls.find((c) => callUrl(c).includes("por-objeto"))!)).toContain(
      "organization_id=3",
    );
  });
});

describe("FiltroEtiquetaSelect", () => {
  it("sin etiquetas en la organización no se pinta", async () => {
    const fetch = stubApi([], {});
    const { container } = render(<FiltroEtiquetaSelect value="todas" onChange={() => {}} />, {
      wrapper,
    });
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("con etiquetas dice qué filtra en su nombre accesible", async () => {
    stubApi([Q4], {});
    render(<FiltroEtiquetaSelect value="todas" onChange={() => {}} alcance="en esta página" />, {
      wrapper,
    });
    expect(
      await screen.findByRole("combobox", { name: "Filtrar por etiqueta en esta página" }),
    ).toBeInTheDocument();
  });
});
