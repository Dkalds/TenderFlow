import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// TopNav wires together many stores/children. We stub the external
// dependencies so TopNav's own markup and handlers run deterministically;
// those dependencies are covered by their own tests.
const setTheme = vi.fn();
const setCommandOpen = vi.fn();
vi.mock("next/navigation", () => ({ usePathname: () => "/resumen" }));
vi.mock("next-themes", () => ({ useTheme: () => ({ theme: "light", setTheme }) }));
vi.mock("@/hooks/use-admin", () => ({ useAdmin: () => true }));
vi.mock("@/lib/filters", () => ({
  useWithFilters: () => (path: string) => path,
}));
vi.mock("@/lib/ui-store", () => ({
  useUiStore: (selector: (s: { setCommandOpen: typeof setCommandOpen }) => unknown) =>
    selector({ setCommandOpen }),
}));
const apiMutate = vi.fn().mockResolvedValue({});
vi.mock("@/lib/api-client", () => ({ apiMutate: (...a: unknown[]) => apiMutate(...a) }));
vi.mock("@/components/notification-bell", () => ({ NotificationBell: () => <div data-testid="bell" /> }));
vi.mock("@/components/export-popover", () => ({ ExportPopover: () => <div data-testid="export" /> }));

import { TopNav } from "@/components/layout/top-nav";

afterEach(() => {
  vi.unstubAllGlobals();
  setTheme.mockClear();
  setCommandOpen.mockClear();
  apiMutate.mockClear();
});

function renderNav() {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ last_extraction: new Date().toISOString() }),
    }),
  );
  return render(<TopNav />);
}

describe("TopNav", () => {
  it("renders the header with theme and density controls", () => {
    renderNav();
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByTestId("bell")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Toggle density/ })).toBeInTheDocument();
  });

  it("toggles the theme when the theme button is clicked", () => {
    renderNav();
    fireEvent.click(screen.getByRole("button", { name: /Toggle theme/ }));
    expect(setTheme).toHaveBeenCalledWith("dark");
  });

  it("opens the command palette from the search button (single search entry point)", () => {
    renderNav();
    fireEvent.click(screen.getByRole("button", { name: /Abrir busqueda y comandos/ }));
    expect(setCommandOpen).toHaveBeenCalledWith(true);
  });

  it("opens the mobile navigation drawer", () => {
    renderNav();
    fireEvent.click(screen.getByRole("button", { name: "Menu" }));
    expect(screen.getByRole("dialog", { name: /Menú de navegación/ })).toBeInTheDocument();
  });

  it("auto-expands the section containing the active page", () => {
    renderNav();
    fireEvent.click(screen.getByRole("button", { name: "Menu" }));
    // pathname is stubbed to "/resumen", which lives in "Inicio".
    const sectionToggle = screen.getByRole("button", { name: /Inicio/ });
    expect(sectionToggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: /Resumen/ })).toBeInTheDocument();
  });

  it("expands and collapses a non-active section without navigating", () => {
    renderNav();
    fireEvent.click(screen.getByRole("button", { name: "Menu" }));
    const mercadoToggle = screen.getByRole("button", { name: /Mercado/ });
    expect(mercadoToggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(mercadoToggle);
    expect(mercadoToggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: /Organos/ })).toBeInTheDocument();
    // The drawer must stay open after expanding a section.
    expect(screen.getByRole("dialog", { name: /Menú de navegación/ })).toBeInTheDocument();

    fireEvent.click(mercadoToggle);
    expect(mercadoToggle).toHaveAttribute("aria-expanded", "false");
  });

  it("closes the mobile drawer when a child page link is clicked", () => {
    renderNav();
    fireEvent.click(screen.getByRole("button", { name: "Menu" }));
    fireEvent.click(screen.getByRole("link", { name: /Resumen/ }));
    expect(screen.queryByRole("dialog", { name: /Menú de navegación/ })).not.toBeInTheDocument();
  });

  it("opens the user menu and logs out", async () => {
    renderNav();
    fireEvent.click(screen.getByRole("button", { name: /Menú de usuario/ }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    const logout = screen.getByRole("menuitem", { name: /logout|cerrar|salir/i });
    fireEvent.click(logout);
    await waitFor(() => expect(apiMutate).toHaveBeenCalledWith("POST", "/api/v1/auth/logout"));
  });

  it("shows the last-extraction relative time once fetched", async () => {
    renderNav();
    await waitFor(() => expect(screen.getByText("Datos en vivo")).toBeInTheDocument());
  });
});
