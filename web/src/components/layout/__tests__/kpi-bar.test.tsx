import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { KpiBar, KpiBarConnected } from "@/components/layout/kpi-bar";

describe("KpiBar (presentational)", () => {
  it("renders loading skeletons when loading", () => {
    const { container } = render(<KpiBar loading />);
    expect(screen.getByRole("region", { name: /Indicadores/ })).toBeInTheDocument();
    expect(container.querySelectorAll('[data-slot="skeleton"], .tf-shimmer').length).toBeGreaterThan(0);
  });

  it("renders a tile per KPI with up/down trend indicators", () => {
    render(
      <KpiBar
        kpis={[
          { label: "Total", value: "1.234" },
          { label: "Crecimiento", value: "10%", trend: 5.2 },
          { label: "Caída", value: "-3%", trend: -3.1 },
        ]}
      />,
    );
    expect(screen.getByText("Total:")).toBeInTheDocument();
    expect(screen.getByText("1.234")).toBeInTheDocument();
    expect(screen.getByText("(subida)")).toBeInTheDocument();
    expect(screen.getByText("(bajada)")).toBeInTheDocument();
  });

  it("renders nothing but the region when no KPIs and not loading", () => {
    render(<KpiBar />);
    expect(screen.getByRole("region", { name: /Indicadores/ })).toBeInTheDocument();
  });
});

describe("KpiBarConnected", () => {
  function renderConnected(overview: unknown) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    if (overview !== undefined) qc.setQueryData(["analytics", "overview"], overview);
    return render(
      <QueryClientProvider client={qc}>
        <KpiBarConnected />
      </QueryClientProvider>,
    );
  }

  it("maps overview data into KPI tiles (billions formatting)", () => {
    renderConnected({
      total_licitaciones: 12345,
      importe_total: 2_500_000_000,
      licitaciones_30d: 321,
      licitaciones_30d_trend: 4.5,
      yoy_delta: 8.2,
    });
    expect(screen.getByText("Total:")).toBeInTheDocument();
    expect(screen.getByText("2.5B €")).toBeInTheDocument();
  });

  it("formats thousands and a negative YoY", () => {
    renderConnected({
      total_licitaciones: 10,
      importe_total: 5000,
      licitaciones_30d: 2,
      yoy_delta: -1.5,
    });
    expect(screen.getByText("5K €")).toBeInTheDocument();
  });
});
