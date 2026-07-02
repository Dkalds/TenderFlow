import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RadarChart } from "@/components/charts/radar-chart";

const DATA = [
  { dimension: "Precio", value: 80 },
  { dimension: "Calidad", value: 60, fullMark: 120 },
  { dimension: "Plazo", value: 40 },
];

describe("RadarChart", () => {
  it("shows an empty-state message when data is empty", () => {
    render(<RadarChart data={[]} />);
    expect(screen.getByText("Sin datos disponibles")).toBeInTheDocument();
  });

  it("renders an accessible chart container when data is provided", () => {
    render(<RadarChart data={DATA} />);
    expect(
      screen.getByRole("img", { name: "Gráfico de radar" }),
    ).toBeInTheDocument();
  });

  it("renders a comparison series when compareData is provided", () => {
    expect(() =>
      render(
        <RadarChart
          data={DATA}
          compareData={[
            { dimension: "Precio", value: 50 },
            { dimension: "Calidad", value: 90 },
            { dimension: "Plazo", value: 70 },
          ]}
          compareName="Rival"
        />,
      ),
    ).not.toThrow();
  });

  it("forwards a custom className", () => {
    render(<RadarChart data={DATA} className="custom-radar" />);
    expect(
      screen.getByRole("img", { name: "Gráfico de radar" }).className,
    ).toContain("custom-radar");
  });
});
