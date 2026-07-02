import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ChartTooltip } from "@/components/charts/chart-tooltip";

describe("ChartTooltip", () => {
  it("returns null when inactive", () => {
    const { container } = render(<ChartTooltip active={false} payload={[{ value: 1 }]} />);
    expect(container.firstChild).toBeNull();
  });

  it("returns null when payload is empty", () => {
    const { container } = render(<ChartTooltip active payload={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders a row per payload entry with name and value", () => {
    render(
      <ChartTooltip
        active
        label="Enero"
        payload={[
          { name: "Importe", value: 100, color: "#f00" },
          { name: "Contratos", value: 5, fill: "#0f0" },
        ]}
      />,
    );
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    expect(screen.getByText("Enero")).toBeInTheDocument();
    expect(screen.getByText("Importe:")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
    expect(screen.getByText("Contratos:")).toBeInTheDocument();
  });

  it("falls back to dataKey when name is missing", () => {
    render(<ChartTooltip active payload={[{ dataKey: "pct", value: 42 }]} />);
    expect(screen.getByText("pct:")).toBeInTheDocument();
  });

  it("applies a string formatter to the value", () => {
    render(
      <ChartTooltip
        active
        payload={[{ name: "Importe", value: 1000 }]}
        formatter={(v) => `€${v}`}
      />,
    );
    expect(screen.getByText("€1000")).toBeInTheDocument();
  });

  it("applies a tuple formatter ([value, name])", () => {
    render(
      <ChartTooltip
        active
        payload={[{ name: "raw", value: 7 }]}
        formatter={() => ["7 uds", "Unidades"]}
      />,
    );
    expect(screen.getByText("Unidades:")).toBeInTheDocument();
    expect(screen.getByText("7 uds")).toBeInTheDocument();
  });

  it("applies an object formatter (ChartTooltipRow)", () => {
    render(
      <ChartTooltip
        active
        payload={[{ name: "raw", value: 7 }]}
        formatter={() => ({ name: "Custom", value: "VAL", color: "#abc" })}
      />,
    );
    expect(screen.getByText("Custom:")).toBeInTheDocument();
    expect(screen.getByText("VAL")).toBeInTheDocument();
  });

  it("supports a labelFormatter", () => {
    render(
      <ChartTooltip
        active
        label="2024"
        payload={[{ name: "x", value: 1 }]}
        labelFormatter={(l) => `Año ${l}`}
      />,
    );
    expect(screen.getByText("Año 2024")).toBeInTheDocument();
  });

  it("hides swatches when hideSwatch is set", () => {
    const { container } = render(
      <ChartTooltip active hideSwatch payload={[{ name: "x", value: 1, color: "#f00" }]} />,
    );
    expect(container.querySelector("span[aria-hidden]")).toBeNull();
  });
});
