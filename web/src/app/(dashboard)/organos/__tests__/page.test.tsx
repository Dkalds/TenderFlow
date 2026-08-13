import * as React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * Lo que fija este suite: el ámbito activo llega a las DOS peticiones de la
 * vista, no sólo al ranking.
 *
 * El drill-down se pedía con un `fetch` desnudo, sin un solo parámetro. Entrando
 * en `/mercado?tecnologia=SAP&vista=organos` y abriendo un órgano, la tabla
 * contaba sus licitaciones SAP y el panel de al lado respondía con el histórico
 * completo del órgano — mismo encabezado, dos universos.
 */

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

// `useFilteredQuery` lee el ámbito de aquí; ExportPopover también.
const mockFilterParams = vi.fn<() => Record<string, string>>();
vi.mock("@/lib/filters", () => ({
  useFilterParams: () => mockFilterParams(),
}));

// Los gráficos no son el sujeto: recharts en jsdom sólo añade ruido y tiempo.
vi.mock("@/components/charts/organos-charts", () => ({
  OrganosRankingChart: () => null,
  OrganosTreemapChart: () => null,
  OrganosAdjudicatariosChart: () => null,
  OrganosEstacionalidadChart: () => null,
}));

import OrganosPage from "../page";

const LISTA = {
  organos: [
    {
      organo_contratacion: "ORG A",
      count: 2,
      importe: 1_500_000,
      pct: 66.67,
      ccaa: "Madrid",
    },
  ],
  total_organos: 1,
  importe_total: 1_500_000,
  concentracion_top10: 100,
  treemap_breakdown: [],
};

const DETALLE = {
  kpis: {
    total_licitaciones: 1,
    importe_total: 1_000_000,
    importe_medio: 1_000_000,
    pct_adjudicado: 100,
    lead_time_medio: 10,
    top_adjudicatario: "CONSULTORA SAP",
    top_adj_importe: 900_000,
  },
  top_adjudicatarios: [{ nombre: "CONSULTORA SAP", count: 1, importe: 900_000 }],
  estacionalidad: [{ mes_numero: 1, count: 1 }],
  top_scored: [],
};

function makeResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

/** El detalle lleva el nombre del órgano en el path; el ranking no. */
const ES_DETALLE = /\/analytics\/organos\/[^?/]/;

/** URLs pedidas hasta ahora, en orden. */
function urls(): string[] {
  return (global.fetch as ReturnType<typeof vi.fn>).mock.calls.map(
    (call) => String(call[0]),
  );
}

function urlDetalle(): string | undefined {
  return urls().find((u) => ES_DETALLE.test(u));
}

function renderPage() {
  // Un solo QueryClient por render: el re-render del cambio de ámbito tiene que
  // refetchear por la key, no porque le hayamos vaciado la caché debajo. El
  // elemento se construye de nuevo en cada pasada — React descarta el re-render
  // si le llega la misma referencia y el cambio de ámbito no llegaría a correr.
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const ui = () =>
    React.createElement(
      QueryClientProvider,
      { client: queryClient },
      React.createElement(OrganosPage),
    );
  const utils = render(ui());
  return { ...utils, rerenderPage: () => utils.rerender(ui()) };
}

beforeEach(() => {
  mockFilterParams.mockReturnValue({});
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>().mockImplementation((input: RequestInfo | URL) =>
      Promise.resolve(makeResponse(ES_DETALLE.test(String(input)) ? DETALLE : LISTA)),
    ),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Órganos — el ámbito llega a las dos peticiones", () => {
  it("pide el ranking con el ámbito activo", async () => {
    mockFilterParams.mockReturnValue({ tecnologia: "SAP" });

    renderPage();

    await waitFor(() => expect(urls().length).toBeGreaterThan(0));
    const url = new URL(urls()[0], "http://localhost");
    expect(url.pathname).toBe("/api/v1/analytics/organos");
    expect(url.searchParams.get("tecnologia")).toBe("SAP");
  });

  it("pide el drill-down con el mismo ámbito que el ranking", async () => {
    mockFilterParams.mockReturnValue({ tecnologia: "SAP", ccaa: "Madrid" });

    renderPage();

    // La fila del listado completo lleva el nombre del órgano en su `title`.
    fireEvent.click(await screen.findByTitle("ORG A"));

    await waitFor(() => expect(urlDetalle()).toBeDefined());

    const detalle = new URL(urlDetalle()!, "http://localhost");
    // El nombre viaja percent-encoded en el path, el ámbito en la query.
    expect(detalle.pathname).toBe("/api/v1/analytics/organos/ORG%20A");
    expect(detalle.searchParams.get("tecnologia")).toBe("SAP");
    expect(detalle.searchParams.get("ccaa")).toBe("Madrid");
  });

  it("vuelve a pedir el drill-down cuando cambia el ámbito", async () => {
    mockFilterParams.mockReturnValue({ tecnologia: "SAP" });

    const { rerenderPage } = renderPage();

    fireEvent.click(await screen.findByTitle("ORG A"));
    await waitFor(() => expect(urlDetalle()).toBeDefined());

    // Cambiar de tecnología no puede dejar el panel anterior en pantalla: los
    // filtros forman parte de la key, así que la query se vuelve a pedir.
    mockFilterParams.mockReturnValue({ tecnologia: "SALESFORCE" });
    rerenderPage();

    await waitFor(() =>
      expect(
        urls().some((u) => ES_DETALLE.test(u) && u.includes("tecnologia=SALESFORCE")),
      ).toBe(true),
    );
  });
});
