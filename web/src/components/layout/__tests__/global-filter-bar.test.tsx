import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const setters = {
  setQ: vi.fn(),
  setRango: vi.fn(),
  setEstados: vi.fn(),
  setCcaas: vi.fn(),
  setTecnologias: vi.fn(),
  setImporteMin: vi.fn(),
  resetFilters: vi.fn(),
};
const filtersStub = {
  q: "",
  rango: { desde: null as string | null, hasta: null as string | null },
  estados: ["PUB"],
  ccaas: ["MD"],
  tecnologias: ["IA"],
  importeMin: null as number | null,
  ...setters,
};
vi.mock("@/lib/filters", () => ({ useFilters: () => filtersStub }));

import { GlobalFilterBar } from "@/components/layout/global-filter-bar";

function renderBar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  qc.setQueryData(["meta-filters"], {
    estado: ["PUB", "ADJ"],
    ccaa: ["MD", "CT"],
    tecnologia: ["IA", "Cloud"],
    cpv: [],
  });
  qc.setQueryData(["saved-views"], []);
  return render(
    <QueryClientProvider client={qc}>
      <GlobalFilterBar />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  Object.values(setters).forEach((fn) => fn.mockClear());
});

describe("GlobalFilterBar", () => {
  it("renders an active filter chip (with a remove button) per selected value", () => {
    renderBar();
    // "MD"/"IA" also appear as <select> options, so assert via the unique chips.
    expect(screen.getByRole("button", { name: "Quitar PUB" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Quitar MD" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Quitar IA" })).toBeInTheDocument();
  });

  it("removes an estado chip via its remove button", () => {
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: "Quitar PUB" }));
    expect(setters.setEstados).toHaveBeenCalledWith([]);
  });

  it("adds a CCAA through the select control", () => {
    renderBar();
    fireEvent.change(screen.getByLabelText("Filtrar por CCAA"), { target: { value: "CT" } });
    expect(setters.setCcaas).toHaveBeenCalledWith(["MD", "CT"]);
  });

  it("updates the date range and minimum amount", () => {
    renderBar();
    fireEvent.change(screen.getByLabelText("Fecha desde"), { target: { value: "2024-01-01" } });
    expect(setters.setRango).toHaveBeenCalledWith({ desde: "2024-01-01", hasta: null });
    fireEvent.change(screen.getByLabelText("Importe minimo"), { target: { value: "50000" } });
    expect(setters.setImporteMin).toHaveBeenCalledWith(50000);
  });

  it("clears all filters via the reset button", () => {
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: /Limpiar/ }));
    expect(setters.resetFilters).toHaveBeenCalled();
  });
});
