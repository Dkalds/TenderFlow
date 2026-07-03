import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useUiStore } from "@/lib/ui-store";

// Only the nuqs-backed useFilters is stubbed (covered by filters-hooks.test);
// the saved-views query/mutation hooks stay real so they get exercised.
const setQ = vi.fn();
const filtersStub = {
  q: "obras",
  rango: { desde: null, hasta: null },
  estados: [] as string[],
  ccaas: [] as string[],
  tecnologias: [] as string[],
  importeMin: null,
  setQ,
  setRango: vi.fn(),
  setEstados: vi.fn(),
  setCcaas: vi.fn(),
  setTecnologias: vi.fn(),
  setImporteMin: vi.fn(),
};
vi.mock("@/lib/filters", () => ({ useFilters: () => filtersStub }));

import { SavedViewsMenu } from "@/components/saved-views-menu";

const VIEWS = [
  { id: 1, name: "Vista A", filters_json: '{"q":"cloud","estados":["PUB"]}', created_at: "2024-01-01" },
  { id: 2, name: "Vista B", filters_json: "{}", created_at: "2024-02-01" },
];

function renderMenu(opts: { views?: unknown; pendingFetch?: boolean } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  if (opts.views !== undefined) qc.setQueryData(["saved-views"], opts.views);
  return render(
    <QueryClientProvider client={qc}>
      <SavedViewsMenu />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  setQ.mockClear();
  useUiStore.setState({ savedViewsOpen: false });
});

describe("SavedViewsMenu", () => {
  it("opens the menu and lists saved views", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    renderMenu({ views: VIEWS });
    fireEvent.click(screen.getByRole("button", { name: /Vistas/ }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(screen.getByText("Vista A")).toBeInTheDocument();
    expect(screen.getByText("Vista B")).toBeInTheDocument();
  });

  it("shows an empty state when there are no views", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    renderMenu({ views: [] });
    fireEvent.click(screen.getByRole("button", { name: /Vistas/ }));
    expect(screen.getByText("No tienes vistas guardadas.")).toBeInTheDocument();
  });

  it("shows a loading state while the query is pending", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    renderMenu();
    fireEvent.click(screen.getByRole("button", { name: /Vistas/ }));
    expect(screen.getByText("Cargando…")).toBeInTheDocument();
  });

  it("applies a saved view's snapshot back onto the filters", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    renderMenu({ views: VIEWS });
    fireEvent.click(screen.getByRole("button", { name: /Vistas/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Vista A/ }));
    // applySnapshot replays the snapshot's q value onto the filter store.
    expect(setQ).toHaveBeenCalledWith("cloud");
  });

  it("submits a new view name (triggers the save mutation)", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: { get: () => "application/json" },
      json: async () => ({ ok: true }),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderMenu({ views: [] });
    fireEvent.click(screen.getByRole("button", { name: /Vistas/ }));
    fireEvent.change(screen.getByLabelText("Nombre de la vista"), {
      target: { value: "Nueva vista" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Guardar vista actual/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  });

  it("opens when the ui store's savedViewsOpen flag is set externally (e.g. from the command palette)", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    renderMenu({ views: VIEWS });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    act(() => {
      useUiStore.getState().openSavedViews();
    });
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("closing via outside click also updates the shared ui store", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    renderMenu({ views: VIEWS });
    fireEvent.click(screen.getByRole("button", { name: /Vistas/ }));
    expect(useUiStore.getState().savedViewsOpen).toBe(true);
    fireEvent.mouseDown(document.body);
    expect(useUiStore.getState().savedViewsOpen).toBe(false);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
