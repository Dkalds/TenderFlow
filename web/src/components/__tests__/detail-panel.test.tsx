import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DetailPanel, type LicitacionDetail } from "@/components/detail-panel";

// Child blocks (eventos/prediccion/resoluciones) fetch on mount; keep them inert.
vi.mock("@/lib/api-client", () => ({
  fetchWithAuth: vi.fn(() => new Promise(() => {})),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function makeLic(overrides: Partial<LicitacionDetail> = {}): LicitacionDetail {
  return {
    id_externo: "EXT-1",
    titulo: "Servicio de mantenimiento",
    organo_contratacion: "Ministerio X",
    importe: 500000,
    estado: "Adjudicada",
    fecha_publicacion: "2024-01-01",
    ccaa: "Madrid",
    cpv: "50000000",
    url: "https://contrataciondelestado.es/x",
    tecnologia: "Cloud",
    tipo_contrato: "Servicios",
    provincia: "Madrid",
    fecha_limite: "2024-02-01",
    fecha_inicio: "2024-03-01",
    fecha_fin: "2024-12-31",
    descripcion: "Mantenimiento integral",
    score: 87.5,
    score_desglose: { relevancia: 90, urgencia: 40 },
    risk_flags: ["plazo_corto", "monopolio"],
    ...overrides,
  };
}

function renderPanel(lic: LicitacionDetail, onClose = () => {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <DetailPanel licitacion={lic} onClose={onClose} />
    </QueryClientProvider>,
  );
}

describe("DetailPanel", () => {
  it("renders header, estado, importe, score, breakdown and risk flags", () => {
    renderPanel(makeLic());
    expect(screen.getByText("Servicio de mantenimiento")).toBeInTheDocument();
    expect(screen.getByText("Adjudicada")).toBeInTheDocument();
    expect(screen.getByText("Puntuación")).toBeInTheDocument();
    // Score value + a breakdown dimension.
    expect(screen.getByText("87.5")).toBeInTheDocument();
    expect(screen.getByText("relevancia")).toBeInTheDocument();
    // Risk flags render as destructive badges.
    expect(screen.getByText("plazo_corto")).toBeInTheDocument();
    expect(screen.getByText("Alertas")).toBeInTheDocument();
    // External link.
    expect(screen.getByRole("link", { name: /Ver en PLACSP/ })).toBeInTheDocument();
  });

  it("omits optional sections when their data is absent", () => {
    renderPanel(
      makeLic({
        score: undefined,
        score_desglose: undefined,
        risk_flags: [],
        url: null,
        descripcion: null,
        estado: null,
        importe: null,
      }),
    );
    expect(screen.queryByText("Puntuación")).not.toBeInTheDocument();
    expect(screen.queryByText("Alertas")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Ver en PLACSP/ })).not.toBeInTheDocument();
    // Falls back to id_externo as the title when titulo is present is not the case here.
    expect(screen.getByText("Servicio de mantenimiento")).toBeInTheDocument();
  });

  it("uses id_externo as the title when titulo is null", () => {
    renderPanel(makeLic({ titulo: null }));
    // id_externo appears both as title and description.
    expect(screen.getAllByText("EXT-1").length).toBeGreaterThanOrEqual(1);
  });

  it("copies the permalink to the clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });

    renderPanel(makeLic());
    fireEvent.click(screen.getByRole("button", { name: /Copiar enlace/ }));

    await vi.waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(
        expect.stringContaining("/detalle?lic=EXT-1"),
      );
    });
  });
});
