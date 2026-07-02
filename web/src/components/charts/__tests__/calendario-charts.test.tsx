import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import {
  CalendarioMonthlyChart,
  CalendarioDowChart,
} from "@/components/charts/calendario-charts";

describe("calendario charts", () => {
  it("renders the monthly chart without throwing", () => {
    expect(() =>
      render(
        <CalendarioMonthlyChart
          data={[
            { mes: "2024-01", publicaciones: 12, importe: 100000 },
            { mes: "2024-02", publicaciones: 8, importe: 54000 },
          ]}
        />,
      ),
    ).not.toThrow();
  });

  it("renders the day-of-week chart without throwing", () => {
    expect(() =>
      render(
        <CalendarioDowChart
          data={[
            { dia: "Lun", promedio: 4.5 },
            { dia: "Mar", promedio: 3.1 },
          ]}
        />,
      ),
    ).not.toThrow();
  });
});
