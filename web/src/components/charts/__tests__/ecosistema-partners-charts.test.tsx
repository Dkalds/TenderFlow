import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import {
  GanadoresCountBarChart,
  GanadoresImporteBarChart,
} from "@/components/charts/ecosistema-partners-charts";

const DATA = [
  { nombre: "Empresa con un nombre muy largo que debe truncarse", count: 30, importe: 900000 },
  { nombre: "ACME S.L.", count: 12, importe: 250000 },
];

describe("ecosistema partners charts", () => {
  it("renders the winners-by-count chart without throwing", () => {
    expect(() => render(<GanadoresCountBarChart data={DATA} />)).not.toThrow();
  });

  it("renders the winners-by-amount chart without throwing", () => {
    expect(() => render(<GanadoresImporteBarChart data={DATA} />)).not.toThrow();
  });
});
