import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PrediccionBajaBlock } from "@/components/prediccion-baja";

function renderWithData(id: string, data: unknown) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (data !== undefined) qc.setQueryData(["prediccion-baja", id], data);
  return render(
    <QueryClientProvider client={qc}>
      <PrediccionBajaBlock licitacionId={id} />
    </QueryClientProvider>,
  );
}

describe("PrediccionBajaBlock", () => {
  it("renders nothing when there is no prediction", () => {
    const { container } = renderWithData("L0", undefined);
    expect(container.firstChild).toBeNull();
  });

  it("renders the model interval with the model badge", () => {
    renderWithData("L1", {
      licitacion_id: "L1",
      p10: 0.05,
      p50: 0.15,
      p90: 0.3,
      model_version: 3,
      computed_at: "2025-01-15T10:00:00Z",
      serving: "modelo",
    });
    expect(screen.getByText("Baja esperada")).toBeInTheDocument();
    expect(screen.getByText("modelo v3")).toBeInTheDocument();
    // Median formatted as a percentage.
    expect(screen.getByText("15.0%")).toBeInTheDocument();
  });

  it("renders the baseline label when serving is baseline", () => {
    renderWithData("L2", {
      licitacion_id: "L2",
      p10: 0.1,
      p50: 0.2,
      p90: 0.4,
      model_version: null,
      computed_at: "2025-02-01T10:00:00Z",
      serving: "baseline",
    });
    expect(screen.getByText("estimación histórica")).toBeInTheDocument();
  });

  it("compares estimated vs real baja for an awarded tender with prior estimate", () => {
    renderWithData("L3", {
      licitacion_id: "L3",
      p10: 0.05,
      p50: 0.12,
      p90: 0.2,
      model_version: 3,
      computed_at: "2025-01-15T10:00:00Z",
      serving: "modelo",
      baja_real: 0.18,
      importe_adjudicado: 82000,
    });
    expect(screen.getByText("Baja estimada vs. real")).toBeInTheDocument();
    expect(screen.getByText("12.0%")).toBeInTheDocument();
    expect(screen.getByText("18.0%")).toBeInTheDocument();
    expect(screen.getByText("+6.0% vs. estimado")).toBeInTheDocument();
  });

  it("renders only the real baja for an awarded tender with no prior estimate", () => {
    renderWithData("L4", { licitacion_id: "L4", baja_real: 0.2, importe_adjudicado: 40000 });
    expect(screen.getByText("Baja real")).toBeInTheDocument();
    expect(screen.getByText("20.0%")).toBeInTheDocument();
    expect(
      screen.getByText("Sin estimación del modelo previa a la adjudicación."),
    ).toBeInTheDocument();
  });
});
