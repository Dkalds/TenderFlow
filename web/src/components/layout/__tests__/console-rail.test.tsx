/**
 * Tests del rail de espacios (`components/layout/console-rail.tsx`).
 *
 * El rail sustituye a la sidebar de 248px, así que lo que hay que demostrar es
 * que no se perdió navegación: los 14 espacios están, Ops sólo si eres admin,
 * Dirección si además diriges la organización activa, y una ruta heredada
 * marca activo el espacio que la absorbió — si no, quien aterrice por un
 * enlace viejo no sabe dónde está.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, cleanup, fireEvent, within } from "@testing-library/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ADMIN_ONLY_SPACES, CONSOLE_SPACES } from "@/lib/console-spaces";

const {
  pathnameRef,
  adminRef,
  organizacionRef,
  setTheme,
  toggleCompact,
  initDensity,
  apiMutate,
  setActiveOrganizationId,
} = vi.hoisted(() => ({
    pathnameRef: { current: "/resumen" },
    adminRef: { current: true },
    organizacionRef: {
      current: { id: 1, name: "Acme", role: "admin", is_personal: false } as {
        id: number;
        name: string;
        role: string;
        is_personal: boolean;
      },
    },
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
  useOrganizations: () => ({ isLoading: false, data: [organizacionRef.current] }),
  useActiveOrganizationId: () => organizacionRef.current.id,
  useOrganizationStore: (selector: (s: unknown) => unknown) => selector({ setActiveOrganizationId }),
}));
vi.mock("@/lib/api-client", () => ({ apiMutate: (...a: unknown[]) => apiMutate(...a) }));
vi.mock("@/lib/report-error", () => ({ reportError: vi.fn() }));

import { ConsoleRail } from "@/components/layout/console-rail";

// El cajón móvil y el selector de organización llegan con `next/dynamic` al
// abrirse (`console-rail.tsx`): el primer import transforma el módulo, y con la
// máquina cargada pasa del segundo por defecto de `findBy*`.
const DESCARGA = { timeout: 15_000 };

const ACME = { id: 1, name: "Acme", role: "admin", is_personal: false };

const renderRail = (pathname = "/resumen", admin = true, organizacion = ACME) => {
  pathnameRef.current = pathname;
  adminRef.current = admin;
  organizacionRef.current = organizacion;
  return render(
    <TooltipProvider>
      <ConsoleRail />
    </TooltipProvider>,
  );
};

/** El rail de escritorio; el cajón móvil pinta los mismos espacios. */
const railNav = () => screen.getByRole("navigation", { name: "Espacios" });

/**
 * En el rail el nombre accesible de un espacio es su nombre, que es también el
 * texto visible bajo el icono (WCAG 2.5.3). Antes era un código de 3 letras
 * seguido de la etiqueta en un `sr-only` («RESResumen»).
 */
const railName = (space: { label: string }) => space.label;
const railLink = (space: { label: string }) =>
  within(railNav()).getByRole("link", { name: railName(space) });
const bySlug = (key: string) => CONSOLE_SPACES.find((space) => space.key === key)!;

beforeEach(() => {
  vi.clearAllMocks();
});
afterEach(() => {
  cleanup();
});

describe("ConsoleRail", () => {
  it("enlaza todos los espacios cuando eres admin", () => {
    renderRail("/resumen", true);
    const links = within(railNav()).getAllByRole("link");
    // 14 espacios + el monograma que lleva al resumen.
    expect(links).toHaveLength(CONSOLE_SPACES.length + 1);
    for (const space of CONSOLE_SPACES) {
      expect(railLink(space)).toHaveAttribute("href", `/${space.slug}`);
    }
  });

  it("esconde a quien no es admin los espacios con `visibility: admin`, y sólo ésos", () => {
    // El recuento sale de `ADMIN_ONLY_SPACES`, que se deriva de las
    // definiciones: cuando Dirección entró como espacio de owner/admin, un
    // número fijo aquí decía que se escondía uno cuando ya se escondían dos.
    // Quien mira es administradora de Acme, así que Dirección (nivel
    // `gestion`) sí sale.
    renderRail("/resumen", false);
    for (const space of CONSOLE_SPACES) {
      const enlace = within(railNav()).queryByRole("link", { name: railName(space) });
      if (ADMIN_ONLY_SPACES.has(space.key)) {
        expect(enlace, `${space.slug} no debería verse sin admin`).not.toBeInTheDocument();
      } else {
        expect(enlace, `${space.slug} debería verse`).toBeInTheDocument();
      }
    }
    // Los visibles más el monograma que lleva al resumen.
    expect(within(railNav()).getAllByRole("link")).toHaveLength(
      CONSOLE_SPACES.length - ADMIN_ONLY_SPACES.size + 1,
    );
  });

  it("la propietaria de un equipo ve Dirección sin ser administradora de la plataforma", () => {
    // El caso que motivó el nivel `gestion`: la API le sirve `/pursuits/direccion`
    // y hasta ahora no había ningún enlace que la llevara allí.
    renderRail("/resumen", false, { ...ACME, role: "owner" });
    expect(railLink(bySlug("direccion"))).toHaveAttribute("href", "/direccion");
    expect(within(railNav()).queryByRole("link", { name: "Ops y Admin" })).not.toBeInTheDocument();
  });

  it("un miembro del equipo no ve Dirección: la API le respondería 403", () => {
    for (const role of ["member", "viewer"]) {
      renderRail("/resumen", false, { ...ACME, role });
      expect(
        within(railNav()).queryByRole("link", { name: "Dirección" }),
        `${role} no debería ver Dirección`,
      ).not.toBeInTheDocument();
      cleanup();
    }
  });

  it("en la organización personal no hay Dirección: no hay equipo que dirigir", () => {
    renderRail("/resumen", false, { id: 9, name: "Personal", role: "owner", is_personal: true });
    expect(within(railNav()).queryByRole("link", { name: "Dirección" })).not.toBeInTheDocument();
  });

  it("el administrador de la plataforma ve Dirección en cualquier organización", () => {
    renderRail("/resumen", true, { ...ACME, role: "viewer" });
    expect(railLink(bySlug("direccion"))).toBeInTheDocument();
  });

  it("pinta el nombre de cada espacio bajo su icono, sin códigos ni texto oculto", () => {
    renderRail("/resumen", true);
    for (const space of CONSOLE_SPACES) {
      const enlace = railLink(space);
      // Lo que se ve es el nombre entero: el nombre accesible no añade nada
      // que no esté en pantalla, y no queda ningún `sr-only` de apoyo.
      expect(enlace).toHaveTextContent(new RegExp(`^${space.label}$`));
      expect(enlace.querySelector(".sr-only")).toBeNull();
      expect(enlace.querySelector(".font-mono")).toBeNull();
    }
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

  it("abre el cajón de navegación en móvil", { timeout: 30_000 }, async () => {
    renderRail("/resumen");
    expect(screen.queryByRole("navigation", { name: "Navegación móvil" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Abrir navegación" }));
    const cajon = await screen.findByRole("navigation", { name: "Navegación móvil" }, DESCARGA);
    expect(within(cajon).getByRole("link", { name: "Radar" })).toBeInTheDocument();
  });

  it("el monograma vuelve al resumen", () => {
    renderRail("/detalle");
    expect(
      within(railNav()).getByRole("link", { name: "TenderFlow · ir al resumen" }),
    ).toHaveAttribute("href", "/resumen");
  });

  it("el rail es una superficie sólida, sin degradado, y su marca no lleva halo", () => {
    renderRail("/resumen");
    const nav = railNav();
    expect(nav).toHaveClass("bg-card");
    expect(nav.className).not.toMatch(/gradient/);
    const marca = within(nav).getByRole("link", { name: "TenderFlow · ir al resumen" });
    // La marca es la de `TenderFlowLogo`, no una copia en línea del trazo.
    expect(marca.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(marca.innerHTML).not.toMatch(/shadow/);
  });

  it("la barra móvil lleva la marca con su wordmark, sin vidrio", () => {
    renderRail("/resumen");
    const barraMovil = screen.getByRole("button", { name: "Abrir navegación" }).parentElement!;
    expect(barraMovil).toHaveClass("bg-background");
    expect(barraMovil.className).not.toContain("tf-glass");
    expect(within(barraMovil).getByText("TenderFlow")).toHaveClass("font-display", "text-tf-lede");
  });

  it("nombra el rol de la organización en castellano", { timeout: 30_000 }, async () => {
    renderRail("/resumen");
    fireEvent.pointerDown(screen.getAllByRole("button", { name: "Menú de cuenta" })[0]);
    expect(await screen.findByRole("combobox", { name: "Organización activa" }, DESCARGA)).toHaveTextContent(
      "Acme · Administrador",
    );
  });

  it("la barra móvil no dibuja separador: el corte con el contenido es de la barra de ámbito", () => {
    // Debajo de esta barra va la de ámbito, no el contenido. Su borde de scroll
    // (12px bajo su borde inferior) se pintaba encima de la barra de ámbito,
    // que ya dibuja el del corte: dos bordes para uno. Y el `border-b` fijo que
    // tuvo antes pintaba la línea también en el tope, donde no separa nada.
    //
    // Sin ningún `[data-scroll-edge]` vale para cualquier estado del scroll: el
    // gradiente se monta siempre y sólo cambia de opacidad.
    const { container } = renderRail("/resumen");
    const barraMovil = screen.getByRole("button", { name: "Abrir navegación" }).parentElement!;

    expect(barraMovil).toHaveClass("md:hidden");
    expect(barraMovil.className).not.toContain("border-b");
    expect(container.querySelector("[data-scroll-edge]")).toBeNull();
  });

  it("arranca la densidad al montar el menú de cuenta", () => {
    renderRail("/resumen");
    expect(initDensity).toHaveBeenCalled();
    // Un menú de cuenta por superficie: el de escritorio y el de la barra móvil.
    expect(screen.getAllByRole("button", { name: "Menú de cuenta" })).toHaveLength(2);
  });

  it("usa un selector Radix accesible para cambiar de organización", { timeout: 30_000 }, async () => {
    renderRail("/resumen");
    fireEvent.pointerDown(screen.getAllByRole("button", { name: "Menú de cuenta" })[0]);

    const selector = await screen.findByRole("combobox", { name: "Organización activa" }, DESCARGA);
    expect(selector.tagName).toBe("BUTTON");
  });
});
