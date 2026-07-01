import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { useUiStore } from "@/lib/ui-store";

const push = vi.fn();
const setTheme = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("next-themes", () => ({ useTheme: () => ({ theme: "light", setTheme }) }));
vi.mock("@/hooks/use-admin", () => ({ useAdmin: () => true }));
vi.mock("@/lib/filters", () => ({ useWithFilters: () => (p: string) => p }));

import { CommandPalette } from "@/components/command-palette";

beforeEach(() => {
  useUiStore.setState({ commandOpen: false });
  push.mockClear();
  setTheme.mockClear();
});
afterEach(() => {
  useUiStore.setState({ commandOpen: false });
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
