import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
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
// pathname y filter params controlables por test (contrato de filtros por página).
const pathnameRef = { current: "/detalle" };
const paramsRef = { current: { estado: "PUB", ccaa: "MD", tecnologia: "IA" } as Record<string, string> };
vi.mock("next/navigation", () => ({ usePathname: () => pathnameRef.current }));
vi.mock("@/lib/filters", () => ({
  useFilters: () => filtersStub,
  useFilterParams: () => paramsRef.current,
}));

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
  pathnameRef.current = "/detalle";
  paramsRef.current = { estado: "PUB", ccaa: "MD", tecnologia: "IA" };
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

  it("adds an estado through the select control", () => {
    renderBar();
    fireEvent.change(screen.getByLabelText("Filtrar por estado"), { target: { value: "ADJ" } });
    expect(setters.setEstados).toHaveBeenCalledWith(["PUB", "ADJ"]);
  });

  it("updates the date range directly", () => {
    renderBar();
    fireEvent.change(screen.getByLabelText("Fecha desde"), { target: { value: "2024-01-01" } });
    expect(setters.setRango).toHaveBeenCalledWith({ desde: "2024-01-01", hasta: null });
  });

  it("applies a date preset via the quick-range menu", () => {
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: /Rangos de fecha rapidos/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Todo" }));
    expect(setters.setRango).toHaveBeenCalledWith({ desde: null, hasta: null });
  });

  it("debounces the minimum amount input before calling setImporteMin", async () => {
    renderBar();
    fireEvent.change(screen.getByLabelText("Importe minimo"), { target: { value: "50000" } });
    expect(setters.setImporteMin).not.toHaveBeenCalled();

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 450));
    });

    expect(setters.setImporteMin).toHaveBeenCalledWith(50000);
  });

  it("applies an amount preset instantly via the preset menu", () => {
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: /Presets de importe minimo/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: "> 500K" }));
    expect(setters.setImporteMin).toHaveBeenCalledWith(500_000);
  });

  it("clears all filters via the reset button", () => {
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: /Limpiar/ }));
    expect(setters.resetFilters).toHaveBeenCalled();
  });

  it("renders nothing on non-filter pages when no filters are active", () => {
    pathnameRef.current = "/administracion";
    paramsRef.current = {};
    const { container } = renderBar();
    expect(container).toBeEmptyDOMElement();
  });

  it("shows an explicit notice on non-filter pages with active filters", () => {
    pathnameRef.current = "/administracion";
    paramsRef.current = { estado: "PUB", ccaa: "MD" };
    renderBar();
    expect(
      screen.getByText(/Los filtros globales no aplican en esta página \(2 activos\)/),
    ).toBeInTheDocument();
    // La barra completa no se renderiza (no hay buscador de licitaciones).
    expect(screen.queryByLabelText("Buscar licitaciones")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Limpiar/ }));
    expect(setters.resetFilters).toHaveBeenCalled();
  });
});
