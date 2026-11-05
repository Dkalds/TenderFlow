import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TecnologiasBlock } from "@/components/tecnologias-block";
import { fetchWithAuth } from "@/lib/api-client";

vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  fetchWithAuth: vi.fn(() => new Promise(() => {})),
}));

function withData(id: string, data: unknown, ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(["tecnologias", id], data);
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const RESULT = {
  id_externo: "L1",
  items: [
    {
      tecnologia: "SAP",
      en_titulo: true,
      ml_probabilidad: 0.92,
      ml_threshold_aplicado: 0.5,
      pliego_keywords_score: null,
      pliego_keywords_terms: null,
      pliego_llm_score: null,
      pliego_llm_evidence: null,
    },
    {
      tecnologia: "META4",
      en_titulo: false,
      ml_probabilidad: null,
      ml_threshold_aplicado: null,
      pliego_keywords_score: 0.75,
      pliego_keywords_terms: ["meta4", "recursos humanos"],
      pliego_llm_score: null,
      pliego_llm_evidence: null,
    },
  ],
};

describe("TecnologiasBlock", () => {
  it("sin tecnologías lo dice, en vez de desaparecer", () => {
    withData("L-empty", { id_externo: "L-empty", items: [] }, <TecnologiasBlock licitacionId="L-empty" />);
    expect(screen.getByText("Tecnologías")).toBeInTheDocument();
    expect(screen.getByText("Sin tecnología detectada")).toBeInTheDocument();
  });

  it("mientras carga pinta el esqueleto, no el vacío", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={qc}>
        <TecnologiasBlock licitacionId="L-carga" />
      </QueryClientProvider>,
    );
    expect(container.querySelector('[data-slot="skeleton"]')).not.toBeNull();
    expect(screen.queryByText("Sin tecnología detectada")).not.toBeInTheDocument();
  });

  it("si la consulta falla lo dice con «Reintentar», no como «sin tecnología»", async () => {
    vi.mocked(fetchWithAuth).mockRejectedValueOnce(new Error("Error del servidor"));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <TecnologiasBlock licitacionId="L-fallo" />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("No se pudo cargar la señal tecnológica")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reintentar/i })).toBeInTheDocument();
    expect(screen.queryByText("Sin tecnología detectada")).not.toBeInTheDocument();
  });

  it("sin título propio cuando el contenedor ya rotula la sección", () => {
    withData("L1", RESULT, <TecnologiasBlock licitacionId="L1" conTitulo={false} />);
    expect(screen.queryByText("Tecnologías")).not.toBeInTheDocument();
    expect(screen.getByText("SAP")).toBeInTheDocument();
  });

  it("renders detected technologies with their origin chips", () => {
    withData("L1", RESULT, <TecnologiasBlock licitacionId="L1" />);
    expect(screen.getByText("Tecnologías")).toBeInTheDocument();
    expect(screen.getByText("SAP")).toBeInTheDocument();
    expect(screen.getByText("META4")).toBeInTheDocument();
    // SAP: detectada en título + ML
    expect(screen.getAllByText("título")).toHaveLength(1);
    expect(screen.getAllByText("ML")).toHaveLength(1);
    // META4: solo detectada en pliego
    expect(screen.getAllByText("pliego")).toHaveLength(1);
  });

  it("expands keyword evidence on click for pliego-only detections", () => {
    withData("L1", RESULT, <TecnologiasBlock licitacionId="L1" />);

    const meta4Button = screen.getByRole("button", { name: /META4/ });
    expect(screen.queryByText(/meta4, recursos humanos/)).not.toBeInTheDocument();

    fireEvent.click(meta4Button);

    expect(screen.getByText(/meta4, recursos humanos/)).toBeInTheDocument();
  });

  it("the title-only technology is not expandable (no evidence)", () => {
    withData("L1", RESULT, <TecnologiasBlock licitacionId="L1" />);

    const sapButton = screen.getByRole("button", { name: /SAP/ });
    expect(sapButton).toBeDisabled();
  });
});
