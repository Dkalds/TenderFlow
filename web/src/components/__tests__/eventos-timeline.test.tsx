import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { EventosTimeline } from "@/components/eventos-timeline";

// Keep the network out of it: the loading test relies on a never-settling query,
// the data/empty tests inject cache entries directly.
vi.mock("@/lib/api-client", () => ({
  fetchWithAuth: vi.fn(() => new Promise(() => {})),
}));

function renderTimeline(id: string, data?: unknown) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (data !== undefined) qc.setQueryData(["eventos", id], data);
  return render(
    <QueryClientProvider client={qc}>
      <EventosTimeline licitacionId={id} />
    </QueryClientProvider>,
  );
}

describe("EventosTimeline", () => {
  it("renders skeletons while loading", () => {
    const { container } = renderTimeline("L-loading");
    expect(container.querySelectorAll('[data-slot="skeleton"], .tf-shimmer').length).toBeGreaterThan(0);
  });

  it("renders an empty message when there are no events", () => {
    renderTimeline("L-empty", { items: [] });
    expect(screen.getByText("Sin eventos registrados.")).toBeInTheDocument();
  });

  it("renders events covering the label/variant maps and importe branches", () => {
    renderTimeline("L-data", {
      items: [
        { fecha: "2024-01-01", tipo: "publicacion", campo: null, valor_antes: null, valor_despues: null, importe_delta: null, detalle: null },
        { fecha: "2024-02-01", tipo: "adjudicacion", campo: null, valor_antes: null, valor_despues: null, importe_delta: 100000, detalle: "Adjudicado a ACME" },
        { fecha: "2024-03-01", tipo: "modificacion", campo: "importe", valor_antes: "100", valor_despues: "120", importe_delta: 20000, detalle: null },
        { fecha: "2024-04-01", tipo: "anulacion", campo: null, valor_antes: null, valor_despues: null, importe_delta: -5000, detalle: null },
        { fecha: "2024-05-01", tipo: "desconocido", campo: null, valor_antes: null, valor_despues: null, importe_delta: null, detalle: null },
      ],
    });
    expect(screen.getByText("Publicación")).toBeInTheDocument();
    expect(screen.getByText("Adjudicación")).toBeInTheDocument();
    expect(screen.getByText("Adjudicado a ACME")).toBeInTheDocument();
    expect(screen.getByText("Modificación")).toBeInTheDocument();
    // Unknown tipo falls back to the raw string.
    expect(screen.getByText("desconocido")).toBeInTheDocument();
    // The modificacion event shows the campo before → after line.
    expect(screen.getByText(/importe: 100 → 120/)).toBeInTheDocument();
  });
});
