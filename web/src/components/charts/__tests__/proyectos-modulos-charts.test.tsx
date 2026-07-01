import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import {
  ModulosBarChart,
  TiposPieChart,
  ModulosTreemap,
  TiposTreemap,
  TipoEstadoStackedChart,
} from "@/components/charts/proyectos-modulos-charts";

describe("proyectos y modulos charts", () => {
  it("renders the modules bar chart", () => {
    expect(() =>
      render(
        <ModulosBarChart
          data={[
            { modulo: "Redes", count: 30, importe: 500000 },
            { modulo: "Cloud", count: 18, importe: 320000 },
          ]}
        />,
      ),
    ).not.toThrow();
  });

  it("renders the types pie chart", () => {
    expect(() =>
      render(
        <TiposPieChart
          data={[
            { tipo: "Obras", count: 40, importe: 900000 },
            { tipo: "Servicios", count: 25, importe: 400000 },
          ]}
        />,
      ),
    ).not.toThrow();
  });

  it("renders both treemaps", () => {
    const data = [
      { name: "A", size: 100 },
      { name: "B", size: 60 },
    ];
    expect(() => render(<ModulosTreemap data={data} />)).not.toThrow();
    expect(() => render(<TiposTreemap data={data} />)).not.toThrow();
  });

  it("renders the type/estado stacked chart with dynamic series", () => {
    expect(() =>
      render(
        <TipoEstadoStackedChart
          data={[
            { tipo: "Obras", Publicada: 10, Adjudicada: 5 },
            { tipo: "Servicios", Publicada: 8, Adjudicada: 3 },
          ]}
          estados={["Publicada", "Adjudicada"]}
        />,
      ),
    ).not.toThrow();
  });
});
