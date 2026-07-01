import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// TopNav wires together many stores/children. We stub the external
// dependencies so TopNav's own markup and handlers run deterministically;
// those dependencies are covered by their own tests.
const setTheme = vi.fn();
vi.mock("next/navigation", () => ({ usePathname: () => "/resumen" }));
vi.mock("next-themes", () => ({ useTheme: () => ({ theme: "light", setTheme }) }));
vi.mock("@/hooks/use-admin", () => ({ useAdmin: () => true }));
vi.mock("@/lib/filters", () => ({
  useFilters: () => ({ q: "", setQ: vi.fn() }),
  useWithFilters: () => (path: string) => path,
}));
vi.mock("@/lib/search-history", () => ({
  useSearchHistory: () => ({ history: [], addToHistory: vi.fn() }),
}));
const apiMutate = vi.fn().mockResolvedValue({});
vi.mock("@/lib/api-client", () => ({ apiMutate: (...a: unknown[]) => apiMutate(...a) }));
vi.mock("@/components/notification-bell", () => ({ NotificationBell: () => <div data-testid="bell" /> }));
vi.mock("@/components/export-popover", () => ({ ExportPopover: () => <div data-testid="export" /> }));
vi.mock("@/components/ui/search-autocomplete", () => ({
  SearchAutocomplete: () => <input aria-label="search-stub" />,
}));

import { TopNav } from "@/components/layout/top-nav";

afterEach(() => {
  vi.unstubAllGlobals();
  setTheme.mockClear();
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
  it("renders the header with theme, locale and density controls", () => {
    renderNav();
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByTestId("bell")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Cambiar idioma/ })).toBeInTheDocument();
  });

  it("toggles the theme when the theme button is clicked", () => {
    renderNav();
    fireEvent.click(screen.getByRole("button", { name: /Toggle theme/ }));
    expect(setTheme).toHaveBeenCalledWith("dark");
  });

  it("opens the mobile navigation drawer", () => {
    renderNav();
    fireEvent.click(screen.getByRole("button", { name: "Menu" }));
    expect(screen.getByRole("dialog", { name: /Menú de navegación/ })).toBeInTheDocument();
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
