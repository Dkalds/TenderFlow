/**
 * CU-28 — el tablero filtra en servidor y dice de qué universo habla.
 *
 * La API va doblada en `fetch` y los hooks son los de verdad: lo que se fija es
 * qué parámetros salen hacia `GET /pursuits` y qué dice la pantalla con lo que
 * vuelve, no cómo filtraría el navegador (ya no filtra).
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { callMethod, callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";
import TableroView from "../_components/tablero-view";
import { FILTROS_VACIOS, TOPE_TABLERO, type FiltrosTablero } from "../_lib/filtros-tablero";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }));
vi.mock("@/hooks/use-organization", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/use-organization")>();
  return { ...actual, useActiveOrganizationId: () => 7 };
});

function oportunidad(id: number, titulo: string) {
  return {
    id,
    organization_id: 7,
    licitacion_id: `EXP-${id}`,
    tender_title: titulo,
    tender_deadline: "2026-10-15T10:00:00Z",
    responsible_user_id: 5,
    responsible_name: "Ana Ruiz",
    status: "identified",
    decision: "pending",
    decision_reason: null,
    offer_price_eur: null,
    outcome: "pending",
    awarded_amount_eur: null,
    outcome_reason: null,
    identified_at: "2026-09-30T10:00:00Z",
    decision_at: null,
    submitted_at: null,
    closed_at: null,
    created_at: "2026-09-30T10:00:00Z",
    updated_at: "2026-09-30T10:00:00Z",
    version: 1,
    comments_count: 0,
  };
}

function servir(listado: { items: unknown[]; total: number }) {
  const fetchMock = vi.fn((...call: unknown[]) => {
    const url = callUrl(call);
    if (url.startsWith("/api/v1/pursuits/metrics")) {
      return Promise.resolve(
        jsonResponse({
          organization_id: 7,
          pipeline_value_eur: 0,
          pipeline_sin_importe: 0,
          prevision_trimestral: {},
          pursuits_won: 0,
          awarded_amount_eur: 0,
        }),
      );
    }
    if (url.startsWith("/api/v1/pursuits")) return Promise.resolve(jsonResponse({ organization_id: 7, limit: 200, offset: 0, ...listado }));
    if (url.startsWith("/api/v1/etiquetas/por-objeto")) return Promise.resolve(jsonResponse({ por_objeto: {} }));
    return Promise.resolve(jsonResponse([]));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function peticionesDelListado(fetchMock: ReturnType<typeof servir>): URLSearchParams[] {
  return fetchMock.mock.calls
    .filter((call) => callMethod(call) === "GET" && /^\/api\/v1\/pursuits(\?|$)/.test(callUrl(call)))
    .map((call) => new URL(callUrl(call), "http://x").searchParams);
}

function montar(filtros: FiltrosTablero, onLimpiar = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <TableroView filtros={filtros} onLimpiar={onLimpiar} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return onLimpiar;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("TableroView", () => {
  it("pide los filtros al servidor en vez de filtrar la página en el navegador", async () => {
    const fetchMock = servir({ items: [oportunidad(1, "Soporte SAP de nóminas")], total: 1 });
    montar({ q: "nóminas", etiqueta: "4", responsable: "5", plazo: "7d" });

    await waitFor(() => expect(peticionesDelListado(fetchMock).length).toBeGreaterThan(0));
    const params = peticionesDelListado(fetchMock).at(-1)!;
    expect(params.get("q")).toBe("nóminas");
    expect(params.get("etiqueta")).toBe("4");
    expect(params.get("responsible_user_id")).toBe("5");
    expect(params.get("plazo")).toBe("7d");
    expect(params.get("limit")).toBe(String(TOPE_TABLERO));
    expect(params.get("organization_id")).toBe("7");
  });

  it("con filtros dice cuántas casan, que la tira es de toda la organización y qué cuenta el plazo", async () => {
    servir({ items: [oportunidad(1, "Soporte SAP de nóminas")], total: 1 });
    montar({ ...FILTROS_VACIOS, plazo: "vencido" });

    expect(
      await screen.findByText(
        "1 oportunidad casa con los filtros; la tira de arriba es de toda la organización. El plazo solo cuenta las abiertas sin presentar.",
      ),
    ).toBeInTheDocument();
  });

  it("si el conjunto no cabe, lo dice en vez de presentar las que caben como todas", async () => {
    servir({ items: [oportunidad(1, "Uno"), oportunidad(2, "Dos")], total: 340 });
    montar(FILTROS_VACIOS);

    expect(await screen.findByText(/Hay 340 oportunidades\./)).toBeInTheDocument();
    expect(screen.getByText(/Se ven las 2 con actividad más reciente/)).toBeInTheDocument();
  });

  it("sin filtros ni recorte no añade ningún aviso", async () => {
    servir({ items: [oportunidad(1, "Uno")], total: 1 });
    montar(FILTROS_VACIOS);

    await screen.findAllByText("Uno");
    expect(screen.queryByText(/casan? con los filtros|Hay \d+ oportunidades/)).not.toBeInTheDocument();
  });

  it("un filtro sin resultados ofrece quitarlo; sin filtros, el vacío de siempre", async () => {
    servir({ items: [], total: 0 });
    const onLimpiar = montar({ ...FILTROS_VACIOS, q: "zzz" });

    fireEvent.click(await screen.findByRole("button", { name: "Quitar filtros" }));
    expect(onLimpiar).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Todavía no hay oportunidades")).not.toBeInTheDocument();
  });
});
