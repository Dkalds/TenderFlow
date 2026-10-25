import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const fetchWithAuth = vi.hoisted(() => vi.fn((_url: string) => new Promise(() => {})));
vi.mock("@/lib/api-client", () => ({ fetchWithAuth }));

// El ámbito vive en nuqs; aquí basta con los estados ya resueltos y su setter.
const scope = vi.hoisted(() => ({
  estados: [] as string[],
  setEstados: vi.fn(),
}));
vi.mock("@/lib/filters", () => ({
  useFilterParams: () => ({}),
  useFilters: () => ({ estados: scope.estados, setEstados: scope.setEstados }),
}));

import { ComposicionPanel, VISIBLES } from "@/app/(dashboard)/resumen/_components/composicion-panel";

/** Misma clave que compone `useFilteredQuery`: baseKey + url + params. */
const CLAVE = ["analytics", "overview", "/api/v1/analytics/overview", {}];

/** Nueve estados, de mayor a menor: los tres últimos quedan tras «Ver los 9». */
const ESTADOS = ["PUB", "RES", "ADJ", "EV", "ANUL", "PRE", "CERR", "BORR", "RARO"];
const porEstado = ESTADOS.map((estado, i) => ({ estado, n: 900 - i * 100 }));

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  qc.setQueryData(CLAVE, { por_estado: porEstado });
  return render(
    <QueryClientProvider client={qc}>
      <ComposicionPanel />
    </QueryClientProvider>,
  );
}

const grupo = () => screen.getByRole("group", { name: "Filtrar el ámbito por estado" });

describe("ComposicionPanel", () => {
  beforeEach(() => {
    scope.estados = [];
    scope.setEstados.mockClear();
  });

  it("muestra los estados mayores y el resto a un clic", () => {
    renderPanel();
    expect(within(grupo()).getAllByRole("button")).toHaveLength(VISIBLES);

    fireEvent.click(screen.getByRole("button", { name: `Ver los ${ESTADOS.length}` }));
    expect(within(grupo()).getAllByRole("button")).toHaveLength(ESTADOS.length);
    expect(screen.getByRole("button", { name: "Ver menos" })).toHaveAttribute("aria-expanded", "true");
  });

  it("no esconde tras «Ver los N» un estado que está filtrando el ámbito", () => {
    // Es el que explica por qué el resto sale atenuado, y su botón lo quita.
    scope.estados = ["RARO"];
    renderPanel();
    const botones = within(grupo()).getAllByRole("button");
    expect(botones).toHaveLength(VISIBLES + 1);
    const filtrado = botones.at(-1)!;
    expect(filtrado).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(filtrado);
    expect(scope.setEstados).toHaveBeenLastCalledWith([]);
  });
});
