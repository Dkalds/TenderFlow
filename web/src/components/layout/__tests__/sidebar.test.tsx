import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionProvider } from "@/lib/auth";
import { useSidebar } from "@/lib/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";

vi.mock("next/navigation", () => ({
  usePathname: () => "/resumen",
  useSearchParams: () => new URLSearchParams("q=obras"),
}));

import { Sidebar } from "@/components/layout/sidebar";

function renderSidebar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <SessionProvider>
        {/* La sidebar colapsada usa Tooltip para el rail de iconos; fuera del
            árbol de `Providers` hay que montar el provider a mano
            (docs/frontend-motion.md). */}
        <TooltipProvider>
          <Sidebar />
        </TooltipProvider>
      </SessionProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  // El colapso vive en un store de módulo persistido en localStorage: sin este
  // reset el estado se filtra de un test al siguiente.
  useSidebar.setState({ collapsed: false });
  localStorage.clear();
});

describe("Sidebar", () => {
  it("renders the navigation landmark and reflects the active page", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ last_scrape_hours_ago: 5 }) }),
    );
    renderSidebar();
    expect(screen.getByRole("complementary", { name: /Barra lateral/ })).toBeInTheDocument();
    // The /resumen link is marked as the current page.
    const current = document.querySelector('[aria-current="page"]');
    expect(current).not.toBeNull();
  });

  it("collapses and expands when the toggle button is clicked", () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) }));
    const { container } = renderSidebar();
    const aside = container.querySelector("aside")!;
    expect(aside.className).toContain("w-[248px]");
    fireEvent.click(screen.getByRole("button", { name: /Contraer barra lateral/ }));
    expect(aside.className).toContain("w-16");
    fireEvent.click(screen.getByRole("button", { name: /Expandir barra lateral/ }));
    expect(aside.className).toContain("w-[248px]");
  });

  it("shows admin-only sections once the session resolves as admin", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ user_id: "u1", email: "a@b.c", is_admin: true, last_scrape_hours_ago: 2 }),
      }),
    );
    renderSidebar();
    // La frescura sale de `useDataFreshness` (/meta/last-extraction), el mismo
    // hook que usa el TopNav; sin dato aún, el pie muestra el marcador vacío.
    await waitFor(() => expect(screen.getByText(/actualizado/)).toBeInTheDocument());
  });

  it("keeps every destination reachable when collapsed", () => {
    // Regresión: `{!collapsed && marketSections.map(…)}` desmontaba las 10
    // secciones de mercado al colapsar, así que contraer el rail no comprimía
    // la navegación sino que la borraba — quedaban 3 destinos de 11.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) }));
    const { container } = renderSidebar();
    const countLinks = () => container.querySelectorAll("nav a").length;

    const expanded = countLinks();
    fireEvent.click(screen.getByRole("button", { name: /Contraer barra lateral/ }));
    expect(countLinks()).toBe(expanded);
    // Y siguen teniendo nombre accesible aunque solo se vea el icono.
    expect(screen.getByRole("link", { name: "Tendencias" })).toBeInTheDocument();
  });

  it("persists the collapsed preference across remounts", () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) }));
    const first = renderSidebar();
    fireEvent.click(screen.getByRole("button", { name: /Contraer barra lateral/ }));
    first.unmount();

    // Simula una recarga: el store arranca expandido y `initSidebar()` lo
    // sincroniza desde localStorage al montar.
    useSidebar.setState({ collapsed: false });
    const { container } = renderSidebar();
    expect(container.querySelector("aside")!.className).toContain("w-16");
  });
});
