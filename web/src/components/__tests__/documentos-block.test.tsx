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
      <DocumentosBlock licitacionId="L-empty2" fichaUrl="https://contrataciondelestado.es/wps/poc?idEvl=abc" />,
    );
    expect(screen.getByRole("link", { name: /ficha de PLACSP/ })).toHaveAttribute(
      "href",
      "https://contrataciondelestado.es/wps/poc?idEvl=abc",
    );
  });

  it.each([
    ["https://contractaciopublica.cat/ca/detall-publicacio/x/1", /ficha de la PSCP/],
    ["https://ted.europa.eu/es/notice/678766-2026/pdf", /anuncio en TED/],
    ["https://www.contratosdegalicia.gal/licitacion?id=1", /plataforma del comprador/],
  ])("names the platform the ficha link actually goes to (%s)", (url, nombre) => {
    withData("L-plataforma", { items: [] }, <DocumentosBlock licitacionId="L-plataforma" fichaUrl={url} />);
    expect(screen.getByRole("link", { name: nombre })).toHaveAttribute("href", url);
    expect(screen.queryByText(/PLACSP/)).not.toBeInTheDocument();
  });

  it("labels the TED notice as such, not as an additional document", () => {
    withData(
      "L-ted",
      {
        items: [
          {
            ...ITEMS.items[0],
            id: 9,
            tipo: "additional",
            uri: "https://ted.europa.eu/es/notice/678766-2026/pdf",
            filename: "Anuncio TED 678766-2026.pdf",
          },
        ],
      },
      <DocumentosBlock licitacionId="L-ted" />,
    );
    expect(screen.getByText(/Anuncio publicado en TED/)).toBeInTheDocument();
    expect(screen.queryByText(/Documento adicional/)).not.toBeInTheDocument();
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

  it("says so, without links, when PLACSP has announced the documents but not published them", () => {
    // PLACSP referencia el pliego desde el anuncio de licitación y contesta 500
    // a sus enlaces hasta publicarlo: ahí un enlace solo lleva a ese error, y
    // el motivo no es que haya caducado.
    const sinPublicar = {
      items: [
        { ...ITEMS.items[0], status: "error", sin_publicar: true },
        { ...ITEMS.items[1], filename: "PPT.pdf", sin_publicar: true },
      ],
    };
    withData(
      "L-sp",
      sinPublicar,
      <DocumentosBlock licitacionId="L-sp" fichaUrl="https://contrataciondelestado.es/wps/poc?idEvl=abc" />,
    );

    expect(screen.getByText(/todavía no ha publicado el pliego/)).toBeInTheDocument();
    expect(screen.getByText("PCAP.pdf")).toBeInTheDocument();
    expect(screen.getByText("PPT.pdf")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /PCAP\.pdf/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /PPT\.pdf/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/puede haber caducado/)).not.toBeInTheDocument();
    // La ficha del expediente sigue siendo la salida, sin prometer «todos»:
    // allí tampoco están todavía.
    expect(screen.getByRole("link", { name: /^Ver en la ficha de PLACSP/ })).toBeInTheDocument();
  });

  it("does not mention the unpublished pliego when every document is available", () => {
    withData("L-ok", ITEMS, <DocumentosBlock licitacionId="L-ok" />);
    expect(screen.queryByText(/todavía no ha publicado/)).not.toBeInTheDocument();
  });

  it("shows the ficha link as a footer when documents are present", () => {
    withData(
      "L2",
      ITEMS,
      <DocumentosBlock licitacionId="L2" fichaUrl="https://contrataciondelestado.es/wps/poc?idEvl=xyz" />,
    );
    expect(screen.getByRole("link", { name: /ficha de PLACSP/ })).toHaveAttribute(
      "href",
      "https://contrataciondelestado.es/wps/poc?idEvl=xyz",
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

  it("marks as «Nuevo» only the document added after the first batch (F5.1)", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-19T12:00:00Z"));
    try {
      withData(
        "L-nuevo",
        {
          items: [
            { ...ITEMS.items[0], created_at: "2026-08-01T10:00:00Z" },
            { ...ITEMS.items[1], created_at: "2026-09-17T10:00:00Z" },
          ],
        },
        <DocumentosBlock licitacionId="L-nuevo" />,
      );
      expect(screen.getAllByText("Nuevo")).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
