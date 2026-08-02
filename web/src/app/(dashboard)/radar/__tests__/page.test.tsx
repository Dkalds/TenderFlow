import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import type { RadarTender } from "@/hooks/use-radar";

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

const createPursuit = vi.fn().mockResolvedValue({ id: 7 });
vi.mock("@/hooks/use-pursuits", () => ({
  useCreatePursuit: () => ({ mutateAsync: createPursuit, isPending: false }),
}));

const addWatchlist = vi.fn().mockResolvedValue({});
const watchedItems: Array<{ id_externo: string }> = [];
vi.mock("@/hooks/use-watchlist-items", () => ({
  useAddWatchlistItem: () => ({ mutateAsync: addWatchlist, isPending: false }),
  useWatchlistItems: () => ({ data: watchedItems }),
}));

const radarState: {
  data?: { items: RadarTender[] };
  isLoading: boolean;
  isRanking: boolean;
  error: unknown;
} = { data: undefined, isLoading: false, isRanking: false, error: null };
vi.mock("@/hooks/use-radar", () => ({ useRadar: () => radarState }));

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

    render(<RadarPage />);

    expect(screen.getByText("Caliente")).toBeInTheDocument();
  });

  it("falls back to the score when there is no band", () => {
    radarState.data = { items: [tender({ score: 61, band: null })] };

    render(<RadarPage />);

    expect(screen.getByText("Score 61")).toBeInTheDocument();
  });

  it("only says 'Sin puntuar' when the tender really has no score", () => {
    render(<RadarPage />);

    expect(screen.getByText("Sin puntuar")).toBeInTheDocument();
  });

  it("shows a skeleton instead of a band while the ranking is still in flight", () => {
    // "Sin puntuar" antes de que llegue el scoring se lee como una categoría
    // del dato, no como "todavía no lo sé".
    radarState.isRanking = true;

    render(<RadarPage />);

    expect(screen.queryByText("Sin puntuar")).not.toBeInTheDocument();
    expect(screen.getByText(/Ordenando por afinidad/)).toBeInTheDocument();
  });

  it("states the scope of the list instead of implying a market-wide ranking", () => {
    render(<RadarPage />);

    expect(screen.getByText(/señales recientes, ordenadas por afinidad/)).toBeInTheDocument();
  });

  it("renders the countdown to the deadline the API now returns", () => {
    const inTenDays = new Date(Date.now() + 10 * 86_400_000).toISOString();
    radarState.data = { items: [tender({ fecha_limite: inTenDays })] };

    render(<RadarPage />);

    expect(screen.getByText(/d para cierre/)).toBeInTheDocument();
  });

  it("says there is no deadline when the tender has none", () => {
    render(<RadarPage />);

    expect(screen.getByText("Sin fecha límite")).toBeInTheDocument();
  });

  it("opens an opportunity and navigates to it", async () => {
    render(<RadarPage />);

    fireEvent.click(screen.getByRole("button", { name: /Abrir oportunidad/ }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/oportunidades/7"));
    expect(createPursuit).toHaveBeenCalledWith({ licitacion_id: "LIC-1" });
  });

  it("reports a failure to open instead of navigating", async () => {
    createPursuit.mockRejectedValueOnce(new Error("403"));

    render(<RadarPage />);
    fireEvent.click(screen.getByRole("button", { name: /Abrir oportunidad/ }));

    await waitFor(() => expect(toastError).toHaveBeenCalledWith("403"));
    expect(push).not.toHaveBeenCalled();
  });

  it("does not re-follow a tender already on the watchlist", () => {
    watchedItems.push({ id_externo: "LIC-1" });

    render(<RadarPage />);

    const follow = screen.getByRole("button", { name: "Siguiendo" });
    expect(follow).toBeDisabled();
    expect(addWatchlist).not.toHaveBeenCalled();
  });

  it("dismisses a tender and can restore it", () => {
    render(<RadarPage />);
    expect(screen.getByText("Mantenimiento SAP")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Descartar/ }));
    expect(screen.queryByText("Mantenimiento SAP")).not.toBeInTheDocument();
    expect(screen.getByText("Radar al día")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Restaurar 1 descartada/ }));
    expect(screen.getByText("Mantenimiento SAP")).toBeInTheDocument();
  });

  it("offers an inline undo and says the dismissal is session-scoped", () => {
    // No hay endpoint de dismiss en el backend, así que el descarte se pierde
    // al recargar. Mientras siga así, la UI lo declara en vez de dejar que el
    // usuario lo crea definitivo, y ofrece deshacer sin buscar la acción masiva.
    render(<RadarPage />);
    fireEvent.click(screen.getByRole("button", { name: /Descartar/ }));

    expect(toastCall).toHaveBeenCalledWith(
      "Señal descartada en esta sesión",
      expect.objectContaining({ action: expect.objectContaining({ label: "Deshacer" }) }),
    );

    // Deshacer devuelve la señal a la lista.
    const { action } = toastCall.mock.calls[0][1] as { action: { onClick: () => void } };
    act(() => action.onClick());
    expect(screen.getByText("Mantenimiento SAP")).toBeInTheDocument();
  });

  it("surfaces a load failure as an alert", () => {
    radarState.data = undefined;
    radarState.error = new Error("backend caído");

    render(<RadarPage />);

    expect(screen.getByRole("alert")).toHaveTextContent("backend caído");
  });
});
