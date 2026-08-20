/**
 * Tests del rail de espacios (`components/layout/console-rail.tsx`).
 *
 * El rail sustituye a la sidebar de 248px, así que lo que hay que demostrar es
 * que no se perdió navegación: los 14 espacios están, Ops sólo si eres admin, y
 * una ruta heredada marca activo el espacio que la absorbió — si no, quien
 * aterrice por un enlace viejo no sabe dónde está.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, cleanup, fireEvent, within } from "@testing-library/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { CONSOLE_SPACES } from "@/lib/console-spaces";

const { pathnameRef, adminRef, setTheme, toggleCompact, initDensity, apiMutate, setActiveOrganizationId } =
  vi.hoisted(() => ({
    pathnameRef: { current: "/resumen" },
    adminRef: { current: true },
    setTheme: vi.fn(),
    toggleCompact: vi.fn(),
    initDensity: vi.fn(),
    apiMutate: vi.fn().mockResolvedValue({}),
    setActiveOrganizationId: vi.fn(),
  }));

vi.mock("next/navigation", () => ({ usePathname: () => pathnameRef.current }));
vi.mock("next-themes", () => ({ useTheme: () => ({ theme: "light", setTheme }) }));
vi.mock("@/hooks/use-admin", () => ({ useAdmin: () => adminRef.current }));
vi.mock("@/lib/filters", () => ({ useWithFilters: () => (path: string) => path }));
vi.mock("@/lib/density", () => ({
  useDensity: () => ({ compact: false, toggleCompact }),
  initDensity,
}));
vi.mock("@/hooks/use-organization", () => ({
  useOrganizations: () => ({ isLoading: false, data: [{ id: 1, name: "Acme", role: "admin" }] }),
  useActiveOrganizationId: () => 1,
  useOrganizationStore: (selector: (s: unknown) => unknown) => selector({ setActiveOrganizationId }),
}));
vi.mock("@/lib/api-client", () => ({ apiMutate: (...a: unknown[]) => apiMutate(...a) }));
vi.mock("@/lib/report-error", () => ({ reportError: vi.fn() }));

import { ConsoleRail } from "@/components/layout/console-rail";

const renderRail = (pathname = "/resumen", admin = true) => {
  pathnameRef.current = pathname;
  adminRef.current = admin;
  return render(
    <TooltipProvider>
      <ConsoleRail />
    </TooltipProvider>,
  );
};

/** El rail de escritorio; el cajón móvil pinta los mismos espacios. */
const railNav = () => screen.getByRole("navigation", { name: "Espacios" });

/**
 * En el rail el nombre accesible de un espacio es su código de 3 letras
 * (texto visible bajo el icono) seguido de la etiqueta en un `sr-only`.
 */
const railName = (space: { short: string; label: string }) => `${space.short}${space.label}`;
const railLink = (space: { short: string; label: string }) =>
  within(railNav()).getByRole("link", { name: railName(space) });
const bySlug = (key: string) => CONSOLE_SPACES.find((space) => space.key === key)!;

beforeEach(() => {
  vi.clearAllMocks();
});
afterEach(() => {
  cleanup();
});

describe("ConsoleRail", () => {
  it("enlaza los 14 espacios cuando eres admin", () => {
    renderRail("/resumen", true);
    const links = within(railNav()).getAllByRole("link");
    // 14 espacios + el monograma que lleva al resumen.
    expect(links).toHaveLength(CONSOLE_SPACES.length + 1);
    for (const space of CONSOLE_SPACES) {
      expect(railLink(space)).toHaveAttribute("href", `/${space.slug}`);
    }
  });

  it("esconde Ops a quien no es admin, y sólo Ops", () => {
    renderRail("/resumen", false);
    expect(
      within(railNav()).queryByRole("link", { name: railName(bySlug("ops")) }),
    ).not.toBeInTheDocument();
    expect(railLink(bySlug("mercado"))).toBeInTheDocument();
    expect(within(railNav()).getAllByRole("link")).toHaveLength(CONSOLE_SPACES.length);
  });

  it("marca activo el espacio de la ruta actual", () => {
    renderRail("/radar");
    expect(railLink(bySlug("radar"))).toHaveAttribute("aria-current", "page");
    expect(railLink(bySlug("mercado"))).not.toHaveAttribute("aria-current");
  });

  it("marca activo el espacio que absorbió una ruta heredada", () => {
    // Quien aterriza en `/tendencias` por un enlace viejo tiene que ver dónde
    // está: el rail marca Mercado, que es el espacio que la absorbió.
    renderRail("/tendencias");
    expect(railLink(bySlug("mercado"))).toHaveAttribute("aria-current", "page");
  });

  it("resuelve el espacio activo por el primer segmento", () => {
    renderRail("/oportunidades/p-1");
    expect(railLink(bySlug("oportunidades"))).toHaveAttribute("aria-current", "page");
  });

  it("no marca nada en una ruta que no pertenece a ningún espacio", () => {
    renderRail("/login");
    for (const space of CONSOLE_SPACES) {
      expect(railLink(space)).not.toHaveAttribute("aria-current");
    }
  });

  it("abre el cajón de navegación en móvil", () => {
    renderRail("/resumen");
    expect(screen.queryByRole("navigation", { name: "Navegación móvil" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Abrir navegación" }));
    const cajon = screen.getByRole("navigation", { name: "Navegación móvil" });
    expect(within(cajon).getByRole("link", { name: "Radar" })).toBeInTheDocument();
  });

  it("el monograma vuelve al resumen", () => {
    renderRail("/detalle");
    expect(
      within(railNav()).getByRole("link", { name: "TenderFlow · ir al resumen" }),
    ).toHaveAttribute("href", "/resumen");
  });

  it("la barra móvil separa con el borde de scroll, no con una línea fija", () => {
    // Es cromo translúcido apoyado sobre el contenido: el `border-b` que tenía
    // pintaba la línea también en el tope, donde no hay nada que separar.
    const { container } = renderRail("/resumen");
    const barraMovil = container.querySelector("[data-scroll-edge]")!.parentElement!;

    expect(barraMovil.className).toContain("md:hidden");
    expect(barraMovil.className).not.toContain("border-b");
    expect(container.querySelector("[data-scroll-edge]")).toHaveAttribute("data-scroll-edge", "off");
  });

  it("arranca la densidad al montar el menú de cuenta", () => {
    renderRail("/resumen");
    expect(initDensity).toHaveBeenCalled();
    // Un menú de cuenta por superficie: el de escritorio y el de la barra móvil.
    expect(screen.getAllByRole("button", { name: "Menú de cuenta" })).toHaveLength(2);
  });
});
