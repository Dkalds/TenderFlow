import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { SankeyChart } from "@/components/charts/sankey-chart";

const NODES = [
  { id: "org::A", label: "Órgano A" },
  { id: "org::B", label: "Órgano B" },
  { id: "emp::X", label: "Empresa X" },
  { id: "emp::Y", label: "Empresa Y" },
];
const LINKS = [
  { source: "org::A", target: "emp::X", value: 10 },
  { source: "org::A", target: "emp::Y", value: 5 },
  { source: "org::B", target: "emp::X", value: 8 },
];

describe("SankeyChart", () => {
  it("renders an accessible SVG diagram with fixed dimensions", () => {
    const { container } = render(
      <SankeyChart nodes={NODES} links={LINKS} width={600} height={400} />,
    );
    const svg = container.querySelector('svg[aria-label="Diagrama Sankey"]');
    expect(svg).not.toBeNull();
  });

  it("draws one node rect per node via the d3 layout effect", () => {
    const { container } = render(
      <SankeyChart nodes={NODES} links={LINKS} width={600} height={400} />,
    );
    const rects = container.querySelectorAll("rect.sankey-node");
    expect(rects.length).toBe(NODES.length);
  });

  it("renders a tooltip element and forwards the className", () => {
    const { container } = render(
      <SankeyChart nodes={NODES} links={LINKS} width={600} height={400} className="sk" />,
    );
    expect(container.querySelector('[role="tooltip"]')).not.toBeNull();
    expect(container.querySelector(".sk")).not.toBeNull();
  });

  it("handles an empty link set without throwing", () => {
    expect(() =>
      render(<SankeyChart nodes={NODES} links={[]} width={600} height={400} />),
    ).not.toThrow();
  });
});
