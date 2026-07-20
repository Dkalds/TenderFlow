import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/api-client", () => ({
  fetchWithAuth: vi.fn(() => new Promise(() => {})),
}));

import { EventosFeed } from "@/app/(dashboard)/pipeline-alertas/_components/eventos-feed";

function renderFeed(data?: unknown) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  if (data !== undefined) qc.setQueryData(["eventos", "feed"], data);
  return render(
    <QueryClientProvider client={qc}>
      <EventosFeed />
    </QueryClientProvider>,
  );
}

describe("EventosFeed", () => {
  it("shows an empty state when there are no events", () => {
    renderFeed({ items: [], dias: 30 });
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders events with their type label and links to the detail page", () => {
    renderFeed({
      items: [
        {
          licitacion_id: "L1",
          tipo: "prorroga",
          fecha: "2026-07-01",
          detalle: null,
          importe_delta: null,
          titulo: "Mantenimiento SAP",
          organo_contratacion: "Ministerio X",
          fuente: "placsp",
        },
      ],
      dias: 30,
    });
    expect(screen.getByText("Prórroga")).toBeInTheDocument();
    const link = screen.getByText("Mantenimiento SAP").closest("a");
    expect(link).toHaveAttribute("href", "/detalle?lic=L1");
  });

  it("shows importe_delta with a sign and color", () => {
    renderFeed({
      items: [
        {
          licitacion_id: "L2",
          tipo: "modificacion",
          fecha: "2026-07-05",
          detalle: null,
          importe_delta: 5000,
          titulo: "Ampliación de suministro",
          organo_contratacion: null,
          fuente: "placsp",
        },
      ],
      dias: 30,
    });
    expect(screen.getByText(/\+/)).toBeInTheDocument();
  });

  it("falls back to the raw tipo when it is unknown", () => {
    renderFeed({
      items: [
        {
          licitacion_id: "L3",
          tipo: "algo_nuevo",
          fecha: null,
          detalle: null,
          importe_delta: null,
          titulo: null,
          organo_contratacion: null,
          fuente: null,
        },
      ],
      dias: 30,
    });
    expect(screen.getByText("algo_nuevo")).toBeInTheDocument();
  });
});
