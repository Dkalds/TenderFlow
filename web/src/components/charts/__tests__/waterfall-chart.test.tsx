import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { WaterfallChart } from "@/components/charts/waterfall-chart";

const DATA = [
  { period: "2023", delta: 100, cumulative: 100 },
  { period: "2024", delta: -30, cumulative: 70 },
  { period: "2025", delta: 50, cumulative: 120 },
];

describe("WaterfallChart", () => {
  it("shows an empty-state message when data is empty", () => {
    render(<WaterfallChart data={[]} />);
    expect(screen.getByText("Sin datos disponibles")).toBeInTheDocument();
  });

  it("renders an accessible chart container when data is provided", () => {
    render(<WaterfallChart data={DATA} />);
    const img = screen.getByRole("img", { name: "Gráfico de cascada" });
    expect(img).toBeInTheDocument();
  });

  it("forwards a custom className to the container", () => {
    render(<WaterfallChart data={DATA} className="custom-wf" />);
    const img = screen.getByRole("img", { name: "Gráfico de cascada" });
    expect(img.className).toContain("custom-wf");
  });

  it("accepts a custom height without throwing", () => {
    expect(() =>
      render(<WaterfallChart data={DATA} height={200} />),
    ).not.toThrow();
  });
});
