import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DocumentosBlock } from "@/components/documentos-block";

vi.mock("@/lib/api-client", () => ({
  fetchWithAuth: vi.fn(() => new Promise(() => {})),
}));

function withData(id: string, data: unknown, ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(["documentos", id], data);
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const ITEMS = {
  items: [
    {
      id: 1,
      tipo: "legal",
      uri: "https://example.org/pcap.pdf",
      filename: "PCAP.pdf",
      content_type: "application/pdf",
      size_bytes: 204800,
      status: "extracted",
      created_at: "2026-01-01T00:00:00Z",
    },
    {
      id: 2,
      tipo: "technical",
      uri: "https://example.org/ppt.pdf",
      filename: null,
      content_type: null,
      size_bytes: null,
      status: "pending",
      created_at: "2026-01-02T00:00:00Z",
    },
  ],
};

describe("DocumentosBlock", () => {
  it("renders nothing when there are no documents and no ficha link", () => {
    const { container } = withData("L-empty", { items: [] }, <DocumentosBlock licitacionId="L-empty" />);
    expect(container.firstChild).toBeNull();
  });

  it("offers the PLACSP ficha when there are no documents but a ficha link", () => {
    withData(
      "L-empty2",
      { items: [] },
      <DocumentosBlock licitacionId="L-empty2" fichaUrl="https://placsp.example/ficha?idEvl=abc" />,
    );
    expect(screen.getByRole("link", { name: /ficha de PLACSP/ })).toHaveAttribute(
      "href",
      "https://placsp.example/ficha?idEvl=abc",
    );
  });

  it("keeps the link on failed documents but flags it as possibly expired", () => {
    // `status: "error"` no significa "enlace muerto": también cubre ficheros
    // que se descargaron bien y nuestro extractor no supo leer (.docx, .zip).
    // Quitarles el href rompería enlaces que el navegador abre sin problema.
    const conError = {
      items: [
        {
          ...ITEMS.items[0],
          status: "error",
        },
      ],
    };
    withData("L-err", conError, <DocumentosBlock licitacionId="L-err" />);

    const link = screen.getByRole("link", { name: /PCAP\.pdf/ });
    expect(link).toHaveAttribute("href", "https://example.org/pcap.pdf");
    expect(screen.getByText(/puede haber caducado/)).toBeInTheDocument();
  });

  it("shows the ficha link as a footer when documents are present", () => {
    withData(
      "L2",
      ITEMS,
      <DocumentosBlock licitacionId="L2" fichaUrl="https://placsp.example/ficha?idEvl=xyz" />,
    );
    expect(screen.getByRole("link", { name: /ficha de PLACSP/ })).toHaveAttribute(
      "href",
      "https://placsp.example/ficha?idEvl=xyz",
    );
  });

  it("renders documents with links to the original source", () => {
    withData("L1", ITEMS, <DocumentosBlock licitacionId="L1" />);
    expect(screen.getByText("Documentos")).toBeInTheDocument();

    const link1 = screen.getByRole("link", { name: /PCAP\.pdf/ });
    expect(link1).toHaveAttribute("href", "https://example.org/pcap.pdf");
    expect(link1).toHaveAttribute("target", "_blank");
    expect(link1).toHaveAttribute("rel", "noopener noreferrer");

    // Second item has no filename → falls back to the tipo label.
    const link2 = screen.getByRole("link", { name: /Pliego técnico/ });
    expect(link2).toHaveAttribute("href", "https://example.org/ppt.pdf");
  });
});
