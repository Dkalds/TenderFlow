import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";

const fetchWithAuth = vi.hoisted(() => vi.fn((_url: string) => new Promise(() => {})));
vi.mock("@/lib/api-client", () => ({ fetchWithAuth }));

// El ámbito vive en nuqs; aquí basta con las CCAA ya resueltas y su setter.
const scope = vi.hoisted(() => ({
  ccaas: [] as string[],
  setCcaas: vi.fn(),
}));
vi.mock("@/lib/filters", () => ({
  useFilterParams: () => ({}),
  useFilters: () => ({ ccaas: scope.ccaas, setCcaas: scope.setCcaas }),
}));

import { ComunidadesPanel, VISIBLES } from "@/app/(dashboard)/resumen/_components/comunidades-panel";

/** Misma clave que compone `useFilteredQuery`: baseKey + url + params. */
const CLAVE = ["analytics", "overview", "/api/v1/analytics/overview", {}];

const COMUNIDADES = [
  "Andalucía",
  "Cataluña",
  "Madrid",
  "Comunidad Valenciana",
  "Galicia",
  "Castilla y León",
  "País Vasco",
  "Canarias",
  "Aragón",
];

function renderPanel(porCcaa?: { ccaa: string; n: number; importe: number }[], concentracion = 0) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  if (porCcaa) qc.setQueryData(CLAVE, { por_ccaa: porCcaa, concentracion_geo_top3: concentracion });
  // `TooltipProvider` por las pistas de las casillas; en la app lo monta el
  // layout del dashboard.
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <ComunidadesPanel />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

const filas = COMUNIDADES.map((ccaa, i) => ({ ccaa, n: 900 - i * 100, importe: 1e6 }));

describe("ComunidadesPanel", () => {
  beforeEach(() => {
    scope.ccaas = [];
    scope.setCcaas.mockClear();
  });

  it("ranks the first communities with their count and share, and shows the rest on demand", () => {
    renderPanel(filas);
    const grupo = screen.getByRole("group", { name: "Filtrar el ámbito por comunidad" });
    const botones = within(grupo).getAllByRole("button");
    expect(botones).toHaveLength(VISIBLES);
    // 900 de 4500 expedientes con comunidad.
    expect(botones[0]).toHaveTextContent(/Andalucía.*900.*20,0\s?%/);

    fireEvent.click(screen.getByRole("button", { name: `Ver las ${COMUNIDADES.length}` }));
    expect(within(grupo).getAllByRole("button")).toHaveLength(COMUNIDADES.length);
    expect(screen.getByRole("button", { name: "Ver menos" })).toHaveAttribute("aria-expanded", "true");
  });

  it("toggles a community in the scope when a row is pressed", () => {
    scope.ccaas = ["Madrid"];
    renderPanel(filas);
    const grupo = screen.getByRole("group", { name: "Filtrar el ámbito por comunidad" });
    fireEvent.click(within(grupo).getByRole("button", { name: /^Andalucía/ }));
    expect(scope.setCcaas).toHaveBeenLastCalledWith(["Madrid", "Andalucía"]);

    const madrid = within(grupo).getByRole("button", { name: /^Madrid/ });
    expect(madrid).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(madrid);
    expect(scope.setCcaas).toHaveBeenLastCalledWith([]);

    fireEvent.click(screen.getByRole("button", { name: "Quitar filtro de comunidad" }));
    expect(scope.setCcaas).toHaveBeenLastCalledWith([]);
  });

  it("draws one tile per community with data, and a tile filters like its row", () => {
    scope.ccaas = [];
    renderPanel(filas, 48.9);
    const mapa = screen.getByRole("group", { name: "Mapa de comunidades" });
    // Las nueve comunidades con dato tienen casilla en la rejilla; las otras diez van vacías.
    expect(within(mapa).getAllByRole("button")).toHaveLength(COMUNIDADES.length);
    fireEvent.click(within(mapa).getByRole("button", { name: "Galicia: 500 expedientes" }));
    expect(scope.setCcaas).toHaveBeenLastCalledWith(["Galicia"]);
    // La concentración la da el backend: el panel solo la escribe.
    expect(screen.getByText(/48,9\s?%/)).toBeInTheDocument();
  });

  it("says so when no file in the scope has a community", () => {
    renderPanel([]);
    expect(screen.getByText("Sin comunidad en el ámbito")).toBeInTheDocument();
  });
});
