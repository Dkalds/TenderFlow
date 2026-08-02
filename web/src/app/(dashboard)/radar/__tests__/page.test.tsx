import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { RadarTender } from "@/hooks/use-radar";

/**
 * El Radar es ahora una consola tabular con inspector en el mismo plano, pero
 * las capacidades que fija este suite son las mismas de antes: la banda que
 * puntuó el backend, el alcance declarado de la lista, seguir / dejar de
 * seguir, descartar con deshacer (y restaurar en bloque), abrir oportunidad y
 * el fallo de carga como alerta.
 */

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const toastSuccess = vi.fn();
const toastError = vi.fn();
const toastCall = vi.fn();
vi.mock("sonner", () => {
  const toast = (...a: unknown[]) => toastCall(...a);
  toast.success = (...a: unknown[]) => toastSuccess(...a);
  toast.error = (...a: unknown[]) => toastError(...a);
  return { toast };
});

const createPursuit = vi.fn().mockResolvedValue({ id: 7, organization_id: 3 });
vi.mock("@/hooks/use-pursuits", () => ({
  useCreatePursuit: () => ({ mutateAsync: createPursuit, isPending: false }),
}));

const addWatchlist = vi.fn();
const removeWatchlist = vi.fn();
const watchedItems: Array<{ id_externo: string }> = [];
vi.mock("@/hooks/use-watchlist-items", () => ({
  useAddWatchlistItem: () => ({ mutate: addWatchlist, mutateAsync: addWatchlist, isPending: false }),
  useRemoveWatchlistItem: () => ({
    mutate: removeWatchlist,
    mutateAsync: removeWatchlist,
    isPending: false,
  }),
  useWatchlistItems: () => ({ data: watchedItems }),
}));

const setActiveOrganizationId = vi.fn();
vi.mock("@/hooks/use-organization", () => ({
  useOrganizationStore: (selector: (s: unknown) => unknown) =>
    selector({ setActiveOrganizationId }),
}));

const refetch = vi.fn();
const radarState: {
  data?: { items: RadarTender[] };
  isLoading: boolean;
  isRanking: boolean;
  error: unknown;
  refetch: typeof refetch;
} = { data: undefined, isLoading: false, isRanking: false, error: null, refetch };
vi.mock("@/hooks/use-radar", () => ({ useRadar: () => radarState }));

// El inspector consulta el histórico del órgano; en jsdom no hay backend, así
// que se devuelve vacío y el panel enseña su estado "sin adjudicaciones".
vi.mock("@/lib/api-client", () => ({ fetchWithAuth: vi.fn().mockResolvedValue({}) }));

// RadarPage lee `filters.tecnologias` vía el hook nuqs-backed `useFilters`;
// se stubea igual que en saved-views-menu.test.tsx para no requerir un
// NuqsAdapter real en jsdom.
const filtersStub = {
  q: "",
  rango: { desde: null, hasta: null },
  estados: [] as string[],
  ccaas: [] as string[],
  tecnologias: [] as string[],
  importeMin: null,
  comparar: false,
  rangoB: { desde: null, hasta: null },
  setQ: vi.fn(),
  setRango: vi.fn(),
  setEstados: vi.fn(),
  setCcaas: vi.fn(),
  setTecnologias: vi.fn(),
  setImporteMin: vi.fn(),
  setComparar: vi.fn(),
  setRangoB: vi.fn(),
  resetFilters: vi.fn(),
};
vi.mock("@/lib/filters", () => ({ useFilters: () => filtersStub }));

import RadarPage from "@/app/(dashboard)/radar/page";

function renderRadar() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <RadarPage />
    </QueryClientProvider>,
  );
}

function tender(overrides: Partial<RadarTender> = {}): RadarTender {
  return {
    id_externo: "LIC-1",
    titulo: "Mantenimiento SAP",
    organo_contratacion: "Ayuntamiento de Madrid",
    importe: 250000,
    estado: "PUB",
    fecha_publicacion: "2026-07-01T00:00:00Z",
    fecha_limite: null,
    ccaa: "MAD",
    cpv: "72000000",
    url: null,
    tecnologia: "SAP",
    ...overrides,
  } as RadarTender;
}

beforeEach(() => {
  radarState.data = { items: [tender()] };
  radarState.isLoading = false;
  radarState.isRanking = false;
  radarState.error = null;
  watchedItems.length = 0;
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("RadarPage", () => {
  it("shows the band the backend scored, not a generic placeholder", () => {
    radarState.data = { items: [tender({ score: 87, band: "Caliente" })] };

    renderRadar();

    expect(screen.getAllByText("Caliente").length).toBeGreaterThan(0);
  });

  it("shows the score even when the backend sent no band", () => {
    radarState.data = { items: [tender({ score: 61, band: null })] };

    renderRadar();

    expect(screen.getAllByText("61").length).toBeGreaterThan(0);
  });

  it("only says 'Sin puntuar' when the tender really has no score", () => {
    renderRadar();

    expect(screen.getByText("Sin puntuar")).toBeInTheDocument();
  });

  it("does not claim a band while the ranking is still in flight", () => {
    // "Sin puntuar" antes de que llegue el scoring se lee como una categoría
    // del dato, no como "todavía no lo sé".
    radarState.isRanking = true;

    renderRadar();

    expect(screen.getByText(/ordenando por afinidad/i)).toBeInTheDocument();
  });

  it("states the scope of the list instead of implying a market-wide ranking", () => {
    renderRadar();

    expect(screen.getByText(/las 24 más recientes, reordenadas por afinidad/)).toBeInTheDocument();
  });

  it("renders the countdown to the deadline the API now returns", () => {
    const inTenDays = new Date(Date.now() + 10 * 86_400_000).toISOString();
    radarState.data = { items: [tender({ fecha_limite: inTenDays })] };

    renderRadar();

    expect(screen.getByText("10 d")).toBeInTheDocument();
  });

  it("says there is no deadline when the tender has none", () => {
    renderRadar();

    expect(screen.getByText(/Sin fecha límite publicada/)).toBeInTheDocument();
  });

  it("opens an opportunity and navigates to it", async () => {
    renderRadar();

    fireEvent.click(screen.getByRole("button", { name: /Abrir oportunidad/ }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/oportunidades/7"));
    expect(createPursuit).toHaveBeenCalledWith({ licitacion_id: "LIC-1" });
  });

  it("reports a failure to open instead of navigating", async () => {
    createPursuit.mockRejectedValueOnce(new Error("403"));

    renderRadar();
    fireEvent.click(screen.getByRole("button", { name: /Abrir oportunidad/ }));

    await waitFor(() => expect(toastError).toHaveBeenCalledWith("403"));
    expect(push).not.toHaveBeenCalled();
  });

  it("lets a followed tender be unfollowed instead of re-added", () => {
    watchedItems.push({ id_externo: "LIC-1" });

    renderRadar();

    // Lo seguido sale de la bandeja y vive en su propio segmento.
    fireEvent.click(screen.getByRole("button", { name: /^Siguiendo\s*1$/ }));
    fireEvent.click(screen.getByRole("button", { name: "Siguiendo" }));

    expect(removeWatchlist).toHaveBeenCalledWith("LIC-1");
    expect(addWatchlist).not.toHaveBeenCalled();
  });

  it("dismisses a tender and can restore it", () => {
    renderRadar();
    expect(screen.getAllByText("Mantenimiento SAP").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Descartar" }));
    expect(screen.queryByText("Mantenimiento SAP")).not.toBeInTheDocument();
    expect(screen.getByText("Bandeja al día")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Restaurar 1 descartada/ }));
    expect(screen.getAllByText("Mantenimiento SAP").length).toBeGreaterThan(0);
  });

  it("offers an inline undo and says the dismissal is session-scoped", () => {
    // No hay endpoint de dismiss en el backend, así que el descarte se pierde
    // al recargar. Mientras siga así, la UI lo declara en vez de dejar que el
    // usuario lo crea definitivo, y ofrece deshacer sin buscar la acción masiva.
    renderRadar();
    fireEvent.click(screen.getByRole("button", { name: "Descartar" }));

    expect(toastCall).toHaveBeenCalledWith(
      "Señal descartada en esta sesión",
      expect.objectContaining({ action: expect.objectContaining({ label: "Deshacer" }) }),
    );

    // Deshacer devuelve la señal a la lista.
    const { action } = toastCall.mock.calls[0][1] as { action: { onClick: () => void } };
    act(() => action.onClick());
    expect(screen.getAllByText("Mantenimiento SAP").length).toBeGreaterThan(0);
  });

  it("surfaces a load failure as an alert", () => {
    radarState.data = undefined;
    radarState.error = new Error("backend caído");

    renderRadar();

    expect(screen.getByRole("alert")).toHaveTextContent("backend caído");
  });

  it("keeps the dismissed tender reachable in its own segment", () => {
    // Descartar no es borrar: la señal sigue estando, en otra bandeja.
    renderRadar();
    fireEvent.click(screen.getByRole("button", { name: "Descartar" }));

    fireEvent.click(screen.getByRole("button", { name: /^Descartadas\s*1$/ }));

    expect(screen.getAllByText("Mantenimiento SAP").length).toBeGreaterThan(0);
  });
});
