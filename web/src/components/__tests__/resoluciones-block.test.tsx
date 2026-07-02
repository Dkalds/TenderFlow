import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ResolucionesBlock, RecurridoBadge } from "@/components/resoluciones-block";

vi.mock("@/lib/api-client", () => ({
  fetchWithAuth: vi.fn(() => new Promise(() => {})),
}));

function withData(id: string, data: unknown, ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(["resoluciones", id], data);
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const ITEMS = {
  items: [
    {
      id: 1,
      tribunal: "tacrc",
      numero_resolucion: "123/2024",
      numero_recurso: "R-9",
      fecha: "2024-06-01",
      sentido: "estimado",
      url_pdf: "https://example.org/res.pdf",
      resumen: "Estimado parcialmente",
    },
    {
      id: 2,
      tribunal: "oarc",
      numero_resolucion: "9/2024",
      numero_recurso: null,
      fecha: null,
      sentido: null,
      url_pdf: null,
      resumen: null,
    },
  ],
};

describe("ResolucionesBlock", () => {
  it("renders nothing when there are no resolutions", () => {
    const { container } = withData("L-empty", { items: [] }, <ResolucionesBlock licitacionId="L-empty" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders resolutions with sentido labels and a PDF link", () => {
    withData("L1", ITEMS, <ResolucionesBlock licitacionId="L1" />);
    expect(screen.getByText("Recursos")).toBeInTheDocument();
    expect(screen.getByText("Estimado")).toBeInTheDocument();
    expect(screen.getByText(/TACRC 123\/2024/)).toBeInTheDocument();
    expect(screen.getByText("Recurso nº R-9")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ver resolución/ })).toHaveAttribute(
      "href",
      "https://example.org/res.pdf",
    );
    // Second item has null sentido → falls back to "Resolución".
    expect(screen.getByText("Resolución")).toBeInTheDocument();
  });
});

describe("RecurridoBadge", () => {
  it("renders nothing when there are no resolutions", () => {
    const { container } = withData("L-empty", { items: [] }, <RecurridoBadge licitacionId="L-empty" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders a badge when resolutions exist", () => {
    withData("L1", ITEMS, <RecurridoBadge licitacionId="L1" />);
    expect(screen.getByText("Recurrido")).toBeInTheDocument();
  });
});
