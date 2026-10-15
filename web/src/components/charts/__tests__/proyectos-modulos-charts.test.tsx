import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import {
  CategoriasBarChart,
  TiposPieChart,
  ImporteTreemap,
  TipoEstadoStackedChart,
} from "@/components/charts/proyectos-modulos-charts";

describe("proyectos y modulos charts", () => {
  it("pinta las barras de familias y de módulos con el mismo gráfico", () => {
    expect(() =>
      render(
        <CategoriasBarChart
          data={[
            { nombre: "Infraestructura, cloud y redes", count: 30 },
            { nombre: "Ciberseguridad", count: 18 },
          ]}
        />,
      ),
    ).not.toThrow();
    expect(() => render(<CategoriasBarChart data={[{ nombre: "FI", count: 3 }]} />)).not.toThrow();
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

  it("renders the importe treemap", () => {
    const data = [
      { name: "A", size: 100 },
      { name: "B", size: 60 },
    ];
    expect(() => render(<ImporteTreemap data={data} />)).not.toThrow();
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
