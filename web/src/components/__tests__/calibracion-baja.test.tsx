import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CalibracionBajaBlock } from "@/components/calibracion-baja";

function renderWithData(data: unknown) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (data !== undefined) qc.setQueryData(["calibracion-baja"], data);
  return render(
    <QueryClientProvider client={qc}>
      <CalibracionBajaBlock />
    </QueryClientProvider>,
  );
}

describe("CalibracionBajaBlock", () => {
  it("renders a loading skeleton while fetching", () => {
    const { container } = renderWithData(undefined);
    expect(container.querySelector(".tf-shimmer")).toBeTruthy();
  });

  it("renders the insuficiente state with n_evaluadas", () => {
    renderWithData({
      estado: "insuficiente",
      cobertura: null,
      cobertura_nominal: 0.8,
      mae_p50: null,
      sesgo_p50: null,
      n_evaluadas: 12,
    });
    expect(screen.getByText("Datos insuficientes")).toBeInTheDocument();
    expect(screen.getByText(/12 evaluadas hasta ahora/)).toBeInTheDocument();
  });

  it("renders the insuficiente state without a count when n_evaluadas is zero", () => {
    renderWithData({
      estado: "insuficiente",
      cobertura: null,
      cobertura_nominal: 0.8,
      mae_p50: null,
      sesgo_p50: null,
      n_evaluadas: 0,
    });
    expect(screen.getByText("Datos insuficientes")).toBeInTheDocument();
    expect(screen.queryByText(/evaluadas hasta ahora/)).not.toBeInTheDocument();
  });

  it("renders the ok state with coverage, MAE and sesgo", () => {
    renderWithData({
      estado: "ok",
      cobertura: 0.82,
      cobertura_nominal: 0.8,
      mae_p50: 0.045,
      sesgo_p50: 0.01,
      n_evaluadas: 57,
    });
    expect(screen.getByText("Bien calibrado")).toBeInTheDocument();
    expect(screen.getByText("82.0%")).toBeInTheDocument();
    expect(screen.getByText(/nominal 80.0%/)).toBeInTheDocument();
    expect(screen.getByText(/MAE p50: 4.5%/)).toBeInTheDocument();
    expect(screen.getByText(/Sesgo p50: \+1.0%/)).toBeInTheDocument();
    expect(screen.getByText("57 licitaciones evaluadas")).toBeInTheDocument();
  });

  it("renders the degradado state with a warning note", () => {
    renderWithData({
      estado: "degradado",
      cobertura: 0.42,
      cobertura_nominal: 0.8,
      mae_p50: 0.15,
      sesgo_p50: -0.08,
      n_evaluadas: 41,
    });
    expect(screen.getByText("Calibración degradada")).toBeInTheDocument();
    expect(screen.getByText("42.0%")).toBeInTheDocument();
    expect(screen.getByText(/Sesgo p50: -8.0%/)).toBeInTheDocument();
    expect(
      screen.getByText(/menos fiables de lo que indican/),
    ).toBeInTheDocument();
  });
});
