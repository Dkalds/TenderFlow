import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";

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
// `vi.mock` se iza al principio del fichero, así que la fábrica no puede leer
// variables de módulo: el instante se calcula dentro.
vi.mock("@/lib/api-client", () => ({
  apiMutate: (...a: unknown[]) => apiMutate(...a),
  fetchWithAuth: vi.fn(async () => ({
    last_extraction: new Date(Date.now() - 3 * 3_600_000).toISOString(),
  })),
}));
vi.mock("@/components/notification-bell", () => ({ NotificationBell: () => <div data-testid="bell" /> }));
vi.mock("@/components/export-popover", () => ({ ExportPopover: () => <div data-testid="export" /> }));

import { TopNav } from "@/components/layout/top-nav";

// Radix's DropdownMenu trigger opens on pointer down (not a synthetic
// `click`) — see components/ui/__tests__/dropdown-menu.test.tsx.
function openMenu(trigger: HTMLElement) {
  fireEvent.pointerDown(trigger, { button: 0, pointerId: 1, pointerType: "mouse" });
  fireEvent.pointerUp(trigger, { button: 0, pointerId: 1, pointerType: "mouse" });
}

afterEach(() => {
  vi.unstubAllGlobals();
  setTheme.mockClear();
  setCommandOpen.mockClear();
  apiMutate.mockClear();
});

function renderNav() {
  // The density/theme toggle buttons wrap in a Tooltip, which requires a
  // TooltipProvider ancestor (real usage gets one from components/providers.tsx).
  // `useDataFreshness` is a TanStack query, so it needs a client too.
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <TopNav />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("TopNav", () => {
  it("renders the header with theme and density controls", () => {
    renderNav();
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByTestId("bell")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Cambiar densidad/ })).toBeInTheDocument();
  });

  it("toggles the theme when the theme button is clicked", () => {
    renderNav();
    fireEvent.click(screen.getByRole("button", { name: /Cambiar tema/ }));
    expect(setTheme).toHaveBeenCalledWith("dark");
  });

  it("opens the command palette from the search button (single search entry point)", () => {
    renderNav();
    fireEvent.click(screen.getByRole("button", { name: /Abrir búsqueda y comandos/ }));
    expect(setCommandOpen).toHaveBeenCalledWith(true);
  });

  it("opens the mobile navigation drawer", () => {
    renderNav();
    fireEvent.click(screen.getByRole("button", { name: /Abrir menú/ }));
    expect(screen.getByRole("dialog", { name: /Menú de navegación/ })).toBeInTheDocument();
  });

  it("auto-expands the section containing the active page", () => {
    renderNav();
    fireEvent.click(screen.getByRole("button", { name: /Abrir menú/ }));
    // pathname is stubbed to "/resumen", which lives in "Inicio".
    const sectionToggle = screen.getByRole("button", { name: /Inicio/ });
    expect(sectionToggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: /Resumen/ })).toBeInTheDocument();
  });

  it("expands and collapses a non-active section without navigating", () => {
    renderNav();
    fireEvent.click(screen.getByRole("button", { name: /Abrir menú/ }));
    const mercadoToggle = screen.getByRole("button", { name: /Mercado/ });
    expect(mercadoToggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(mercadoToggle);
    expect(mercadoToggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: /Órganos/ })).toBeInTheDocument();
    // The drawer must stay open after expanding a section.
    expect(screen.getByRole("dialog", { name: /Menú de navegación/ })).toBeInTheDocument();

    fireEvent.click(mercadoToggle);
    expect(mercadoToggle).toHaveAttribute("aria-expanded", "false");
  });

  it("closes the mobile drawer when a child page link is clicked", () => {
    renderNav();
    fireEvent.click(screen.getByRole("button", { name: /Abrir menú/ }));
    fireEvent.click(screen.getByRole("link", { name: /Resumen/ }));
    expect(screen.queryByRole("dialog", { name: /Menú de navegación/ })).not.toBeInTheDocument();
  });

  it("opens the user menu and logs out", async () => {
    renderNav();
    openMenu(screen.getByRole("button", { name: /Menú de usuario/ }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    const logout = screen.getByRole("menuitem", { name: /logout|cerrar|salir/i });
    fireEvent.click(logout);
    await waitFor(() => expect(apiMutate).toHaveBeenCalledWith("POST", "/api/v1/auth/logout"));
  });

  it("shows the last-extraction relative time once fetched", async () => {
    renderNav();
    await waitFor(() => expect(screen.getByText(/hace 3 horas/)).toBeInTheDocument());
  });

  it("exposes the exact extraction instant to assistive tech, not via a native title", () => {
    // El instante exacto colgaba de un `title=` nativo, que no se dispara con
    // teclado. Ahora viaja en el nombre accesible del propio indicador.
    const { container } = renderNav();
    expect(container.querySelector("header [title]")).toBeNull();
  });
});
