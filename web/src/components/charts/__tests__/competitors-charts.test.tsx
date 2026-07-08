import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import {
  CompetitorsBarChart,
  CompetitorsPieChart,
  CompetitorsScatterChart,
  CompetitorsTreemap,
  CompetitorsPositioningChart,
  CompetitorsEstacionalidadChart,
} from "@/components/charts/competitors-charts";

describe("competitors charts", () => {
  it("renders the bar chart", () => {
    expect(() =>
      render(
        <CompetitorsBarChart
          data={[
            { nombre: "Empresa con un nombre extremadamente largo", count: 30 },
            { nombre: "ACME", count: 12 },
          ]}
        />,
      ),
    ).not.toThrow();
  });

  it("renders the pie chart", () => {
    expect(() =>
      render(
        <CompetitorsPieChart
          data={[
            { name: "A", value: 900000 },
            { name: "B", value: 400000 },
          ]}
        />,
      ),
    ).not.toThrow();
  });

  it("renders the scatter chart with a top-5 highlight set", () => {
    expect(() =>
      render(
        <CompetitorsScatterChart
          data={[
            { nombre: "A", ticket_medio: 50000, n_organos: 12 },
            { nombre: "B", ticket_medio: 30000, n_organos: 5 },
          ]}
          top5Names={new Set(["A"])}
        />,
      ),
    ).not.toThrow();
  });

  it("renders the treemap", () => {
    expect(() =>
      render(
        <CompetitorsTreemap
          data={[
            { name: "A", size: 900000, count: 30 },
            { name: "B", size: 400000, count: 12 },
          ]}
        />,
      ),
    ).not.toThrow();
  });

  it("renders the positioning chart (computes its own top-5 set)", () => {
    expect(() =>
      render(
        <CompetitorsPositioningChart
          data={[
            { nombre: "A", baja_media: 12.5, importe_medio: 80000, count: 30, pct_monopolio: 20 },
            { nombre: "B", baja_media: 8.1, importe_medio: 40000, count: 12, pct_monopolio: 10 },
          ]}
        />,
      ),
    ).not.toThrow();
  });

  it("renders the seasonality chart", () => {
    expect(() =>
      render(
        <CompetitorsEstacionalidadChart
          data={[
            { mes: "Ene", count: 5, importe: 100000 },
            { mes: "Feb", count: 8, importe: 220000 },
          ]}
        />,
      ),
    ).not.toThrow();
  });
});
