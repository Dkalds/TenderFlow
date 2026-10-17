import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

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

function renderPanel(porCcaa?: { ccaa: string; n: number; importe: number }[]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  if (porCcaa) qc.setQueryData(CLAVE, { por_ccaa: porCcaa });
  return render(
    <QueryClientProvider client={qc}>
      <ComunidadesPanel />
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
    fireEvent.click(screen.getByRole("button", { name: /^Andalucía/ }));
    expect(scope.setCcaas).toHaveBeenLastCalledWith(["Madrid", "Andalucía"]);

    const madrid = screen.getByRole("button", { name: /^Madrid/ });
    expect(madrid).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(madrid);
    expect(scope.setCcaas).toHaveBeenLastCalledWith([]);

    fireEvent.click(screen.getByRole("button", { name: "Quitar filtro de comunidad" }));
    expect(scope.setCcaas).toHaveBeenLastCalledWith([]);
  });

  it("says so when no file in the scope has a community", () => {
    renderPanel([]);
    expect(screen.getByText("Sin comunidad en el ámbito")).toBeInTheDocument();
  });
});
