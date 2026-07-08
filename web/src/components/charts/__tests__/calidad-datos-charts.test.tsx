import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { CalidadCompletenessChart } from "@/components/charts/calidad-datos-charts";

const DATA = [
  { columna: "importe", pct: 95 },
  { columna: "cpv", pct: 78 },
  { columna: "organo", pct: 42 },
];

describe("CalidadCompletenessChart", () => {
  it("renders without throwing for a range of completeness values", () => {
    // Values spanning the three color bands (>=90, >=70, <70) exercise barColor.
    expect(() => render(<CalidadCompletenessChart data={DATA} />)).not.toThrow();
  });

  it("renders with an empty dataset without throwing", () => {
    expect(() => render(<CalidadCompletenessChart data={[]} />)).not.toThrow();
  });
});
