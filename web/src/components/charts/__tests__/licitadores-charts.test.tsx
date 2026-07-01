import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import {
  LicitadoresRankingBarChart,
  LicitadoresGeoCcaaChart,
  LicitadoresEstacionalidadChart,
  LicitadoresTop10ImporteChart,
} from "@/components/charts/licitadores-charts";

describe("licitadores charts", () => {
  it("renders the ranking bar chart", () => {
    expect(() =>
      render(
        <LicitadoresRankingBarChart
          data={[
            { nombre: "Empresa con nombre larguísimo que se trunca", count: 20, importe: 500000 },
            { nombre: "ACME", count: 10, importe: 200000 },
          ]}
        />,
      ),
    ).not.toThrow();
  });

  it("renders the geo-by-ccaa chart", () => {
    expect(() =>
      render(
        <LicitadoresGeoCcaaChart
          data={[
            { ccaa: "Madrid", count: 30 },
            { ccaa: "Galicia", count: 12 },
          ]}
        />,
      ),
    ).not.toThrow();
  });

  it("renders the seasonality composed chart", () => {
    expect(() =>
      render(
        <LicitadoresEstacionalidadChart
          data={[
            { mes: "Ene", count: 5, importe: 100000 },
            { mes: "Feb", count: 8, importe: 220000 },
          ]}
        />,
      ),
    ).not.toThrow();
  });

  it("renders the top-10-by-amount chart", () => {
    expect(() =>
      render(
        <LicitadoresTop10ImporteChart
          data={[
            { nombre: "Empresa A", importe: 900000, count: 12, importe_medio: 75000 },
          ]}
        />,
      ),
    ).not.toThrow();
  });
});
