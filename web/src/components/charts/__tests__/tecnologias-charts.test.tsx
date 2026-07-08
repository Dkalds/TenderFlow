import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import {
  TecnologiasEvolutionChart,
  TecnologiasVolumeBarChart,
  TecnologiasImporteBarChart,
  TecnologiasDonutChart,
  TecnologiasGeoBarChart,
} from "@/components/charts/tecnologias-charts";

const VOLUME = [
  { tecnologia: "IA", count: 30, importe: 500000, importe_medio: 16000, pct: 40, pct_adjudicado: 20, _color: "#4f46e5" },
  { tecnologia: "Cloud", count: 20, importe: 300000, importe_medio: 15000, pct: 25, pct_adjudicado: 12, _color: "#059669" },
];

describe("tecnologias charts", () => {
  it("renders the evolution area chart for both trend metrics", () => {
    const data = [
      { mes: "Ene", IA: 5, Cloud: 3 },
      { mes: "Feb", IA: 8, Cloud: 6 },
    ];
    expect(() =>
      render(<TecnologiasEvolutionChart data={data} techs={["IA", "Cloud"]} trendMetric="count" />),
    ).not.toThrow();
    expect(() =>
      render(<TecnologiasEvolutionChart data={data} techs={["IA", "Cloud"]} trendMetric="importe" />),
    ).not.toThrow();
  });

  it("renders the volume and importe bar charts", () => {
    expect(() => render(<TecnologiasVolumeBarChart data={VOLUME} />)).not.toThrow();
    expect(() => render(<TecnologiasImporteBarChart data={VOLUME} />)).not.toThrow();
  });

  it("renders the donut chart", () => {
    expect(() =>
      render(
        <TecnologiasDonutChart
          data={[
            { tecnologia: "IA", count: 30, importe: 500000 },
            { tecnologia: "Cloud", count: 20, importe: 300000 },
          ]}
        />,
      ),
    ).not.toThrow();
  });

  it("renders the geo bar chart with dynamic tech series", () => {
    expect(() =>
      render(
        <TecnologiasGeoBarChart
          data={[
            { ccaa: "Madrid", IA: 10, Cloud: 6 },
            { ccaa: "Galicia", IA: 4, Cloud: 2 },
          ]}
          techs={["IA", "Cloud"]}
        />,
      ),
    ).not.toThrow();
  });
});
