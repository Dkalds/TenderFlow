import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import {
  PipelineHorizonChart,
  PipelineQuarterlyChart,
  PipelineForecastChart,
  PipelineUrgencyScatter,
} from "@/components/charts/pipeline-charts";

describe("pipeline charts", () => {
  it("renders the horizon chart across all color bands", () => {
    // Each label exercises a different branch of horizonColor().
    expect(() =>
      render(
        <PipelineHorizonChart
          data={[
            { horizonte: "0-7d", count: 5, importe: 100 },
            { horizonte: "7-30d", count: 8, importe: 200 },
            { horizonte: "30-90d", count: 3, importe: 300 },
            { horizonte: "90+d", count: 2, importe: 400 },
            { horizonte: "otro", count: 1, importe: 50 },
          ]}
        />,
      ),
    ).not.toThrow();
  });

  it("renders the quarterly composed chart", () => {
    expect(() =>
      render(
        <PipelineQuarterlyChart
          data={[
            { trimestre: "2024-Q1", count: 10, importe: 500000 },
            { trimestre: "2024-Q2", count: 14, importe: 720000 },
          ]}
        />,
      ),
    ).not.toThrow();
  });

  it("renders the forecast chart bridging history and forecast", () => {
    const data = [
      { mes: "Ene", valor: 10, tipo: "historico", lower: null, upper: null },
      { mes: "Feb", valor: 12, tipo: "historico", lower: null, upper: null },
      { mes: "Mar", valor: 14, tipo: "forecast", lower: 10, upper: 18 },
    ];
    expect(() => render(<PipelineForecastChart data={data} metric="count" />)).not.toThrow();
    expect(() => render(<PipelineForecastChart data={data} metric="sum" />)).not.toThrow();
  });

  it("renders the urgency scatter chart", () => {
    expect(() =>
      render(
        <PipelineUrgencyScatter
          data={[
            { id_externo: "1", titulo: "Urgente", dias_restantes: 3, importe: 100000, es_urgente: true },
            { id_externo: "2", titulo: "Normal", dias_restantes: 45, importe: 50000, es_urgente: false },
          ]}
          onPointClick={() => {}}
        />,
      ),
    ).not.toThrow();
  });
});
