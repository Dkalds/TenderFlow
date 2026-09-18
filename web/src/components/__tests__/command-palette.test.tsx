import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useUiStore } from "@/lib/ui-store";

const { apiGet, registrarEvento } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  registrarEvento: vi.fn(),
}));
vi.mock("@/lib/api-client", () => ({ apiGet }));
vi.mock("@/lib/analytics", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/analytics")>()),
  registrarEvento,
}));
vi.mock("@/hooks/use-organization", () => ({ useActiveOrganizationId: () => 7 }));

const push = vi.fn();
const setTheme = vi.fn();
const writeText = vi.fn();
let filterParamsStub: Record<string, string> = {};
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("next-themes", () => ({ useTheme: () => ({ theme: "light", setTheme }) }));
vi.mock("@/hooks/use-admin", () => ({ useAdmin: () => true }));
vi.mock("@/lib/filters", () => ({
  useWithFilters: () => (p: string) => p,
  useFilterParams: () => filterParamsStub,
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { CommandPalette } from "@/components/command-palette";
import { toast } from "sonner";

function renderPalette() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <CommandPalette />
    </QueryClientProvider>,
  );
}

// `triggerDownload` arma el fichero desde un blob, así que jsdom necesita las
// dos mitades que no implementa: la respuesta y el object URL.
const fetchSpy = vi.fn();

beforeEach(() => {
  useUiStore.setState({ commandOpen: false, savedViewsOpen: false });
  fetchSpy.mockReset();
  fetchSpy.mockResolvedValue(
    new Response("id;titulo", { status: 200, headers: { "Content-Type": "text/csv" } }),
  );
  vi.stubGlobal("fetch", fetchSpy);
  URL.createObjectURL = vi.fn(() => "blob:stub");
  URL.revokeObjectURL = vi.fn();
  push.mockClear();
  apiGet.mockReset();
  registrarEvento.mockReset();
  setTheme.mockClear();
  writeText.mockClear();
  vi.mocked(toast.success).mockClear();
  filterParamsStub = {};
  Object.assign(navigator, { clipboard: { writeText } });
});
afterEach(() => {
  useUiStore.setState({ commandOpen: false, savedViewsOpen: false });
});

describe("CommandPalette", () => {
  it("renders nothing while the store flag is closed", () => {
    const { container } = renderPalette();
    expect(container.firstChild).toBeNull();
  });

  it("renders the palette dialog with action items when open", () => {
    useUiStore.setState({ commandOpen: true });
    renderPalette();
    expect(screen.getByRole("dialog", { name: /Paleta de comandos/ })).toBeInTheDocument();
    expect(screen.getByText("Abrir copiloto")).toBeInTheDocument();
    expect(screen.getByText(/Cambiar tema/)).toBeInTheDocument();
  });

  it("navigates when a section page item is selected", () => {
    useUiStore.setState({ commandOpen: true });
    renderPalette();
    // "Resumen" is a dashboard page item; selecting it routes and closes.
    fireEvent.click(screen.getByText("Resumen"));
    expect(push).toHaveBeenCalled();
    expect(useUiStore.getState().commandOpen).toBe(false);
  });

  it("toggles the theme from the palette", () => {
    useUiStore.setState({ commandOpen: true });
    renderPalette();
    fireEvent.click(screen.getByText(/Cambiar tema/));
    expect(setTheme).toHaveBeenCalledWith("dark");
  });

  it("shows a 'jump to licitación' item for id-like queries", () => {
    useUiStore.setState({ commandOpen: true });
    renderPalette();
    fireEvent.change(screen.getByPlaceholderText(/Buscar páginas/), {
      target: { value: "ES-2024-12345" },
    });
    expect(screen.getByText("Saltar a")).toBeInTheDocument();
  });
});

describe("CommandPalette — Acciones con filtros", () => {
  it("does not render the group when there are no active filters", () => {
    filterParamsStub = {};
    useUiStore.setState({ commandOpen: true });
    renderPalette();
    expect(screen.queryByText("Acciones con filtros")).not.toBeInTheDocument();
  });

  it("renders the group when at least one filter is active", () => {
    filterParamsStub = { q: "obras" };
    useUiStore.setState({ commandOpen: true });
    renderPalette();
    expect(screen.getByText("Acciones con filtros")).toBeInTheDocument();
    expect(screen.getByText("Guardar vista actual")).toBeInTheDocument();
    expect(
      screen.getByText("Crear regla de watchlist con estos filtros"),
    ).toBeInTheDocument();
    expect(screen.getByText("Exportar CSV (vista actual)")).toBeInTheDocument();
    expect(screen.getByText("Exportar Excel (vista actual)")).toBeInTheDocument();
    expect(screen.getByText("Copiar enlace con filtros")).toBeInTheDocument();
  });

  it("'Guardar vista actual' opens the saved views popover and closes the palette", () => {
    filterParamsStub = { q: "obras" };
    useUiStore.setState({ commandOpen: true });
    renderPalette();
    fireEvent.click(screen.getByText("Guardar vista actual"));
    expect(useUiStore.getState().savedViewsOpen).toBe(true);
    expect(useUiStore.getState().commandOpen).toBe(false);
  });

  it("'Crear regla de watchlist' navigates to mi-watchlist with an encoded prefill param", () => {
    filterParamsStub = { q: "obras", estado: "PUB" };
    useUiStore.setState({ commandOpen: true });
    renderPalette();
    fireEvent.click(screen.getByText("Crear regla de watchlist con estos filtros"));
    expect(push).toHaveBeenCalledWith(
      `/mi-watchlist?prefill=${encodeURIComponent(JSON.stringify(filterParamsStub))}`,
    );
  });

  // La descarga dejó de ser un `<a download>` a ciegas: ahora pasa por `fetch`,
  // comprueba `res.ok` y sólo entonces arma el ancla. Estos dos tests afirman
  // sobre la URL pedida y no sobre el click, que es lo que de verdad importa —
  // el bug que motivó el cambio era mandar `format=xlsx`, un valor que la API
  // rechaza con 422, y espiar el click no lo habría detectado nunca.
  it("'Exportar CSV (vista actual)' pide el CSV con los filtros activos", async () => {
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    filterParamsStub = { q: "obras" };
    useUiStore.setState({ commandOpen: true });
    renderPalette();
    fireEvent.click(screen.getByText("Exportar CSV (vista actual)"));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    const url = new URL(fetchSpy.mock.calls[0][0] as string, "http://localhost");
    expect(url.searchParams.get("format")).toBe("csv");
    expect(url.searchParams.get("q")).toBe("obras");
    await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1));
    clickSpy.mockRestore();
  });

  it("'Exportar Excel (vista actual)' lo pide como `excel`, no como `xlsx`", async () => {
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    filterParamsStub = { q: "obras" };
    useUiStore.setState({ commandOpen: true });
    renderPalette();
    fireEvent.click(screen.getByText("Exportar Excel (vista actual)"));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    const url = new URL(fetchSpy.mock.calls[0][0] as string, "http://localhost");
    expect(url.searchParams.get("format")).toBe("excel");
    await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1));
    clickSpy.mockRestore();
  });

  it("'Copiar enlace con filtros' copies the current URL and shows a toast", () => {
    filterParamsStub = { q: "obras" };
    useUiStore.setState({ commandOpen: true });
    renderPalette();
    fireEvent.click(screen.getByText("Copiar enlace con filtros"));
    expect(writeText).toHaveBeenCalledWith(window.location.href);
    expect(toast.success).toHaveBeenCalledWith("Enlace copiado");
  });
});

describe("CommandPalette — búsqueda global (F1.2)", () => {
  function teclear(valor: string) {
    fireEvent.change(screen.getByPlaceholderText(/Buscar páginas/), { target: { value: valor } });
  }

  it("pide /search/global con la organización activa y agrupa por tipo", async () => {
    apiGet.mockResolvedValue({
      q: "indra",
      resultados: [
        { tipo: "empresa", id: "42", titulo: "Indra Soluciones", subtitulo: "A28599033", exacto: false },
        { tipo: "organo", id: "ayto madrid", titulo: "Ayuntamiento de Madrid", subtitulo: "12", exacto: false },
        { tipo: "oportunidad", id: "9", titulo: "Soporte SAP Indra", subtitulo: "qualifying", exacto: false },
      ],
      por_tipo: { empresa: 1, organo: 1, oportunidad: 1 },
      tipos_buscados: ["expediente", "empresa", "organo", "oportunidad"],
    });
    useUiStore.setState({ commandOpen: true });
    renderPalette();
    teclear("indra");

    await waitFor(() => expect(screen.getByText("Indra Soluciones")).toBeInTheDocument());
    expect(apiGet).toHaveBeenCalledWith(
      "/api/v1/search/global",
      expect.objectContaining({
        params: { query: { q: "indra", limit: 5, organization_id: 7 } },
      }),
    );
    expect(screen.getByText("Empresas")).toBeInTheDocument();
    expect(screen.getByText("Órganos")).toBeInTheDocument();
    expect(screen.getByText("12 expedientes")).toBeInTheDocument();
    expect(screen.getByText("Oportunidades de tu equipo")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Indra Soluciones"));
    expect(push).toHaveBeenCalledWith("/competidores/empresa/42");
    expect(registrarEvento).toHaveBeenCalledWith("busqueda_realizada", {
      superficie: "paleta",
      con_resultados: "si",
      tipo_resultado: "empresa",
    });
    expect(useUiStore.getState().commandOpen).toBe(false);
  });

  it("un órgano abre el ranking de órganos con el filtro sembrado", async () => {
    apiGet.mockResolvedValue({
      q: "madrid",
      resultados: [{ tipo: "organo", id: "ayto madrid", titulo: "Ayuntamiento de Madrid", exacto: false }],
      por_tipo: { organo: 1 },
      tipos_buscados: ["expediente", "empresa", "organo", "oportunidad"],
    });
    useUiStore.setState({ commandOpen: true });
    renderPalette();
    teclear("madrid");

    fireEvent.click(await screen.findByText("Ayuntamiento de Madrid"));
    expect(push).toHaveBeenCalledWith(
      `/mercado?vista=organos&organo_q=${encodeURIComponent("Ayuntamiento de Madrid")}`,
    );
  });

  it("un NIF exacto abre el perfil sin pasar por la lista", async () => {
    apiGet.mockResolvedValue({
      q: "A28599033",
      resultados: [{ tipo: "empresa", id: "42", titulo: "Indra", subtitulo: "A28599033", exacto: true }],
      por_tipo: { empresa: 1 },
      tipos_buscados: ["expediente", "empresa", "organo", "oportunidad"],
    });
    useUiStore.setState({ commandOpen: true });
    renderPalette();
    teclear("A28599033");

    await waitFor(() => expect(push).toHaveBeenCalledWith("/competidores/empresa/42"));
    expect(useUiStore.getState().commandOpen).toBe(false);
  });

  it("sin coincidencias dice qué buscó y ofrece buscar en licitaciones", async () => {
    apiGet.mockResolvedValue({
      q: "zzzz",
      resultados: [],
      por_tipo: {},
      tipos_buscados: ["expediente", "empresa", "organo"],
    });
    useUiStore.setState({ commandOpen: true });
    renderPalette();
    teclear("zzzz");

    const aviso = await screen.findByText(/Sin coincidencias para «zzzz»/);
    expect(aviso).toHaveTextContent("en expedientes, empresas y órganos.");
    // Sin `oportunidad` en lo buscado, la paleta no deja creer que el equipo no tiene ninguna.
    expect(aviso).toHaveTextContent("Sin organización activa no se buscan oportunidades.");

    fireEvent.click(screen.getByText(/en licitaciones/));
    expect(push).toHaveBeenCalledWith("/detalle?q=zzzz");
    expect(registrarEvento).toHaveBeenCalledWith("busqueda_realizada", {
      superficie: "paleta",
      con_resultados: "no",
    });
  });

  it("no consulta con menos de tres caracteres", async () => {
    useUiStore.setState({ commandOpen: true });
    renderPalette();
    teclear("in");
    await new Promise((resolve) => setTimeout(resolve, 350));
    expect(apiGet).not.toHaveBeenCalled();
  });
});
