import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { useUiStore } from "@/lib/ui-store";

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
vi.mock("sonner", () => ({ toast: { success: vi.fn() } }));

import { CommandPalette } from "@/components/command-palette";
import { toast } from "sonner";

beforeEach(() => {
  useUiStore.setState({ commandOpen: false, savedViewsOpen: false });
  push.mockClear();
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
    const { container } = render(<CommandPalette />);
    expect(container.firstChild).toBeNull();
  });

  it("renders the palette dialog with action items when open", () => {
    useUiStore.setState({ commandOpen: true });
    render(<CommandPalette />);
    expect(screen.getByRole("dialog", { name: /Paleta de comandos/ })).toBeInTheDocument();
    expect(screen.getByText("Abrir copiloto")).toBeInTheDocument();
    expect(screen.getByText(/Cambiar tema/)).toBeInTheDocument();
  });

  it("navigates when a section page item is selected", () => {
    useUiStore.setState({ commandOpen: true });
    render(<CommandPalette />);
    // "Resumen" is a dashboard page item; selecting it routes and closes.
    fireEvent.click(screen.getByText("Resumen"));
    expect(push).toHaveBeenCalled();
    expect(useUiStore.getState().commandOpen).toBe(false);
  });

  it("toggles the theme from the palette", () => {
    useUiStore.setState({ commandOpen: true });
    render(<CommandPalette />);
    fireEvent.click(screen.getByText(/Cambiar tema/));
    expect(setTheme).toHaveBeenCalledWith("dark");
  });

  it("shows a 'jump to licitación' item for id-like queries", () => {
    useUiStore.setState({ commandOpen: true });
    render(<CommandPalette />);
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
    render(<CommandPalette />);
    expect(screen.queryByText("Acciones con filtros")).not.toBeInTheDocument();
  });

  it("renders the group when at least one filter is active", () => {
    filterParamsStub = { q: "obras" };
    useUiStore.setState({ commandOpen: true });
    render(<CommandPalette />);
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
    render(<CommandPalette />);
    fireEvent.click(screen.getByText("Guardar vista actual"));
    expect(useUiStore.getState().savedViewsOpen).toBe(true);
    expect(useUiStore.getState().commandOpen).toBe(false);
  });

  it("'Crear regla de watchlist' navigates to mi-watchlist with an encoded prefill param", () => {
    filterParamsStub = { q: "obras", estado: "PUB" };
    useUiStore.setState({ commandOpen: true });
    render(<CommandPalette />);
    fireEvent.click(screen.getByText("Crear regla de watchlist con estos filtros"));
    expect(push).toHaveBeenCalledWith(
      `/mi-watchlist?prefill=${encodeURIComponent(JSON.stringify(filterParamsStub))}`,
    );
  });

  it("'Exportar CSV (vista actual)' triggers a CSV download", () => {
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    filterParamsStub = { q: "obras" };
    useUiStore.setState({ commandOpen: true });
    render(<CommandPalette />);
    fireEvent.click(screen.getByText("Exportar CSV (vista actual)"));
    expect(clickSpy).toHaveBeenCalledTimes(1);
    clickSpy.mockRestore();
  });

  it("'Exportar Excel (vista actual)' triggers an Excel download", () => {
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    filterParamsStub = { q: "obras" };
    useUiStore.setState({ commandOpen: true });
    render(<CommandPalette />);
    fireEvent.click(screen.getByText("Exportar Excel (vista actual)"));
    expect(clickSpy).toHaveBeenCalledTimes(1);
    clickSpy.mockRestore();
  });

  it("'Copiar enlace con filtros' copies the current URL and shows a toast", () => {
    filterParamsStub = { q: "obras" };
    useUiStore.setState({ commandOpen: true });
    render(<CommandPalette />);
    fireEvent.click(screen.getByText("Copiar enlace con filtros"));
    expect(writeText).toHaveBeenCalledWith(window.location.href);
    expect(toast.success).toHaveBeenCalledWith("Enlace copiado");
  });
});
