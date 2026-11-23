/**
 * Tests de la barra inferior de móvil (`components/layout/barra-inferior.tsx`).
 *
 * Por debajo de `md` es la navegación entre espacios: lo que hay que demostrar
 * es que no se pierde ninguno (los cuatro del triaje van fijos y el resto en
 * «Más») y que el usuario sabe dónde está aunque el espacio no tenga botón
 * propio.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, within } from "@testing-library/react";
import { CONSOLE_SPACES, isSpaceVisible } from "@/lib/console-spaces";

const { pathnameRef, registrarEvento } = vi.hoisted(() => ({
  pathnameRef: { current: "/radar" },
  registrarEvento: vi.fn(),
}));

vi.mock("next/navigation", () => ({ usePathname: () => pathnameRef.current }));
vi.mock("@/lib/filters", () => ({ useWithFilters: () => (path: string) => path }));
vi.mock("@/lib/analytics", () => ({ registrarEvento }));
// Sin admin ni organización que dirigir: los espacios `core`.
vi.mock("@/hooks/use-acceso-espacios", () => ({
  useAccesoEspacios: () => ({ isAdmin: false, gestionaOrganizacion: false }),
}));

import { BarraInferior, ESPACIOS_BARRA_INFERIOR } from "@/components/layout/barra-inferior";

// La hoja «Más» llega con `next/dynamic` al abrirse.
const DESCARGA = { timeout: 15_000 };

const renderBarra = (pathname: string) => {
  pathnameRef.current = pathname;
  return render(<BarraInferior />);
};

const barra = () => screen.getByRole("navigation", { name: "Navegación principal" });

afterEach(() => {
  cleanup();
  registrarEvento.mockClear();
});

describe("BarraInferior", () => {
  it("lleva fijos los cuatro espacios del triaje y «Más», y solo existe por debajo de md", () => {
    renderBarra("/radar");
    const nav = barra();
    expect(nav).toHaveClass("md:hidden");
    expect(within(nav).getAllByRole("link").map((enlace) => enlace.textContent)).toEqual(
      Object.values(ESPACIOS_BARRA_INFERIOR),
    );
    expect(within(nav).getByRole("button", { name: "Más" })).toHaveAttribute("aria-haspopup", "dialog");
  });

  it("marca el espacio activo", () => {
    renderBarra("/mi-pipeline");
    expect(within(barra()).getByRole("link", { name: "Agenda" })).toHaveAttribute("aria-current", "page");
    cleanup();
    renderBarra("/radar");
    expect(within(barra()).getByRole("link", { name: "Radar" })).toHaveAttribute("aria-current", "page");
    expect(within(barra()).getByRole("link", { name: "Agenda" })).not.toHaveAttribute("aria-current");
  });

  it.each([
    ["/mercado", "Mercado"],
    // Subruta: el espacio sale del primer segmento.
    ["/oportunidades/1", "Oportunidades"],
  ])("en %s, sin botón propio, el activo es «Más» y se dice, no solo se pinta", (ruta, espacio) => {
    renderBarra(ruta);
    for (const enlace of within(barra()).getAllByRole("link")) {
      expect(enlace).not.toHaveAttribute("aria-current");
    }
    const mas = within(barra()).getByRole("button", { name: `Más, estás en ${espacio}` });
    expect(mas).toHaveClass("text-foreground");
  });

  it("cada destino se nombra como el espacio, igual que en la hoja «Más»", () => {
    renderBarra("/resumen");
    const watchlist = within(barra()).getByRole("link", { name: "Mi Watchlist" });
    expect(watchlist).toHaveTextContent("Watchlist");
  });

  it("«Más» abre todos los espacios visibles, con el activo marcado", { timeout: 30_000 }, async () => {
    renderBarra("/mercado");
    fireEvent.click(within(barra()).getByRole("button", { name: /^Más/ }));
    const hoja = await screen.findByRole("navigation", { name: "Navegación móvil" }, DESCARGA);
    const visibles = CONSOLE_SPACES.filter((space) => isSpaceVisible(space, { isAdmin: false, gestionaOrganizacion: false }));
    expect(within(hoja).getAllByRole("link")).toHaveLength(visibles.length);
    expect(within(hoja).getByRole("link", { name: "Mercado" })).toHaveAttribute("aria-current", "page");
  });

  it("mide la navegación desde la barra con su propio origen", () => {
    renderBarra("/resumen");
    fireEvent.click(within(barra()).getByRole("link", { name: "Radar" }));
    expect(registrarEvento).toHaveBeenCalledWith("espacio_abierto", { espacio: "radar", origen: "barra_inferior" });
  });
});
