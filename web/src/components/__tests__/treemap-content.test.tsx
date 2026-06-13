import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { TreemapContent } from "@/components/charts/treemap-content";
import { CHART_SERIES } from "@/lib/chart-colors";

function renderInSvg(ui: React.ReactElement) {
  return render(<svg>{ui}</svg>);
}

describe("TreemapContent", () => {
  it("returns null when width < minWidth (default 40)", () => {
    const { container } = renderInSvg(
      <TreemapContent x={0} y={0} width={30} height={50} name="Test" value={100} index={0} />
    );
    expect(container.querySelector("g")).toBeNull();
  });

  it("returns null when height < minHeight (default 25)", () => {
    const { container } = renderInSvg(
      <TreemapContent x={0} y={0} width={80} height={20} name="Test" value={100} index={0} />
    );
    expect(container.querySelector("g")).toBeNull();
  });

  it("returns null when both width and height are below minimums", () => {
    const { container } = renderInSvg(
      <TreemapContent x={0} y={0} width={10} height={10} name="Test" value={100} index={0} />
    );
    expect(container.querySelector("g")).toBeNull();
  });

  it("renders a rect element when dimensions meet minimums", () => {
    const { container } = renderInSvg(
      <TreemapContent x={0} y={0} width={100} height={60} name="Test" value={100} index={0} />
    );
    const rect = container.querySelector("rect");
    expect(rect).not.toBeNull();
  });

  it("rect has the correct fill color from getSeriesColor(index)", () => {
    const { container } = renderInSvg(
      <TreemapContent x={0} y={0} width={100} height={60} name="Test" value={42} index={0} />
    );
    const rect = container.querySelector("rect");
    expect(rect?.getAttribute("fill")).toBe(CHART_SERIES[0]);
  });

  it("rect fill color changes with different index values", () => {
    const { container } = renderInSvg(
      <TreemapContent x={0} y={0} width={100} height={60} name="Test" value={42} index={2} />
    );
    const rect = container.querySelector("rect");
    expect(rect?.getAttribute("fill")).toBe(CHART_SERIES[2]);
  });

  it("renders name text in the first text element", () => {
    const { container } = renderInSvg(
      <TreemapContent x={0} y={0} width={200} height={80} name="MyLabel" value={99} index={0} />
    );
    const texts = container.querySelectorAll("text");
    expect(texts.length).toBeGreaterThanOrEqual(1);
    expect(texts[0].textContent).toContain("MyLabel");
  });

  it("truncates name when it exceeds cell width", () => {
    // With fontSize=12, width=60: maxChars = floor(60 / (12 * 0.6)) = floor(60/7.2) = 8
    // A name longer than 8 chars gets truncated
    const longName = "VeryLongNameThatShouldBeTruncated";
    const { container } = renderInSvg(
      <TreemapContent x={0} y={0} width={60} height={60} name={longName} value={10} index={0} fontSize={12} />
    );
    const texts = container.querySelectorAll("text");
    expect(texts[0].textContent).toContain("…");
    expect(texts[0].textContent!.length).toBeLessThan(longName.length);
  });

  it("does not truncate short names", () => {
    const { container } = renderInSvg(
      <TreemapContent x={0} y={0} width={200} height={80} name="Short" value={10} index={0} />
    );
    const texts = container.querySelectorAll("text");
    expect(texts[0].textContent).toBe("Short");
  });

  it("renders formatted value text using default String formatter", () => {
    const { container } = renderInSvg(
      <TreemapContent x={0} y={0} width={100} height={80} name="Test" value={42} index={0} />
    );
    const texts = container.querySelectorAll("text");
    // Second text element shows value; height(80) > minHeight(25)+14 = 39, so it renders
    expect(texts.length).toBeGreaterThanOrEqual(2);
    expect(texts[1].textContent).toBe("42");
  });

  it("uses a custom formatValue function", () => {
    const { container } = renderInSvg(
      <TreemapContent
        x={0} y={0} width={100} height={80} name="Test" value={1000} index={0}
        formatValue={(v) => `€${v.toLocaleString()}`}
      />
    );
    const texts = container.querySelectorAll("text");
    expect(texts[1].textContent).toContain("€");
  });

  it("value text is not rendered when height is too small", () => {
    // height=40 — minHeight=25, so 40 > 25+14=39 → renders; height=38 → does not
    const { container } = renderInSvg(
      <TreemapContent x={0} y={0} width={100} height={38} name="Test" value={99} index={0} />
    );
    const texts = container.querySelectorAll("text");
    // Only name text, value text absent
    expect(texts.length).toBe(1);
  });

  it("applies custom borderRadius and opacity to rect", () => {
    const { container } = renderInSvg(
      <TreemapContent x={0} y={0} width={100} height={60} name="T" value={1} index={0} borderRadius={8} opacity={0.5} />
    );
    const rect = container.querySelector("rect");
    expect(rect?.getAttribute("rx")).toBe("8");
    expect(rect?.getAttribute("opacity")).toBe("0.5");
  });

  it("respects custom minWidth / minHeight props", () => {
    // Should render with minWidth=20 even if width=30
    const { container } = renderInSvg(
      <TreemapContent x={0} y={0} width={30} height={50} name="T" value={1} index={0} minWidth={20} />
    );
    expect(container.querySelector("g")).not.toBeNull();
  });
});
