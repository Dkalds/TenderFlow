import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import {
  GeografiaBarChart,
  GeografiaPieChart,
} from "@/components/charts/geografia-charts";

const BAR = [
  { ccaa: "Madrid", count: 100, importe: 900000, pct: 40 },
  { ccaa: "Cataluña", count: 80, importe: 700000, pct: 30 },
];
const PIE = [
  { ccaa: "Madrid", importe: 900000 },
  { ccaa: "Cataluña", importe: 700000 },
];

describe("geografia charts", () => {
  it("renders the bar chart without an onSelect handler", () => {
    expect(() => render(<GeografiaBarChart data={BAR} />)).not.toThrow();
  });

  it("renders the bar chart with an onSelect handler (cursor-pointer)", () => {
    expect(() =>
      render(<GeografiaBarChart data={BAR} onSelect={() => {}} />),
    ).not.toThrow();
  });

  it("renders the pie chart with and without onSelect", () => {
    expect(() => render(<GeografiaPieChart data={PIE} />)).not.toThrow();
    expect(() =>
      render(<GeografiaPieChart data={PIE} onSelect={() => {}} />),
    ).not.toThrow();
  });
});
