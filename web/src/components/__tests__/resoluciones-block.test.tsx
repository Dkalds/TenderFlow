import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ResolucionesBlock, RecurridoBadge } from "@/components/resoluciones-block";
import { apiGet } from "@/lib/api-client";

vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  apiGet: vi.fn(() => new Promise(() => {})),
}));

function sinDatos(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

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
  it("sin resoluciones dice que no consta ninguna", () => {
    withData("L-empty", { items: [] }, <ResolucionesBlock licitacionId="L-empty" />);
    expect(screen.getByText("Sin recursos registrados")).toBeInTheDocument();
  });

  it("mientras carga pinta el esqueleto, no el vacío", () => {
    const { container } = sinDatos(<ResolucionesBlock licitacionId="L-carga" />);
    expect(container.querySelector('[data-slot="skeleton"]')).not.toBeNull();
    expect(screen.queryByText("Sin recursos registrados")).not.toBeInTheDocument();
  });

  it("si /resoluciones falla lo dice en línea: no puede parecer «sin recursos»", async () => {
    vi.mocked(apiGet).mockRejectedValueOnce(new Error("Error del servidor"));
    sinDatos(<ResolucionesBlock licitacionId="L-fallo" />);
    expect(await screen.findByText("No se pudo comprobar si hay recursos")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reintentar/i })).toBeInTheDocument();
    expect(screen.queryByText("Sin recursos registrados")).not.toBeInTheDocument();
  });

  it("un url_pdf que no es http(s) no llega a ser un enlace", () => {
    withData(
      "L-js",
      { items: [{ ...ITEMS.items[0], url_pdf: "javascript:alert(1)" }] },
      <ResolucionesBlock licitacionId="L-js" />,
    );
    expect(screen.getByText("Estimado")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Ver resolución/ })).not.toBeInTheDocument();
  });

  it("un tribunal o número que falta no rompe la fila", () => {
    withData(
      "L-nulos",
      { items: [{ ...ITEMS.items[1], id: 9, tribunal: null, numero_resolucion: null }] },
      <ResolucionesBlock licitacionId="L-nulos" />,
    );
    expect(screen.getAllByText("Resolución").length).toBeGreaterThan(0);
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

  it("mientras carga no reserva sitio en la cabecera", () => {
    const { container } = sinDatos(<RecurridoBadge licitacionId="L-carga-badge" />);
    expect(container.firstChild).toBeNull();
  });

  it("si la consulta falla no calla: dice que los recursos están sin comprobar", async () => {
    vi.mocked(apiGet).mockRejectedValueOnce(new Error("Error del servidor"));
    sinDatos(<RecurridoBadge licitacionId="L-fallo-badge" />);
    expect(await screen.findByText("Recursos sin comprobar")).toBeInTheDocument();
  });
});
