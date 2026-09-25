/**
 * Tests del conmutador de vistas de un espacio (`components/layout/space-shell.tsx`).
 *
 * La regla que fijan: la vista vive en `?vista=`, no en el path. De ahí sale
 * todo lo demás — cambiar de corte no navega, así que el ámbito y la selección
 * sobreviven, y el botón "atrás" no se llena de cortes.
 *
 * Y no navega de verdad: `?vista=` se escribe con `history.replaceState` y no
 * con el router, que en un dashboard `force-dynamic` pedía un RSC al servidor
 * por clic. `next/navigation` es aquí el doble de `test/navegacion-superficial`,
 * que reproduce cómo Next lleva ese cambio a `useSearchParams`: los tests
 * comprueban la URL, que la pantalla se entera y que el router no se toca.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { act, render, screen, cleanup, renderHook, fireEvent } from "@testing-library/react";
import { CONSOLE_SPACES } from "@/lib/console-spaces";
import { SPACE_VIEWS } from "@/lib/space-views";
import { SpaceShell, useSpaceView } from "@/components/layout/space-shell";
import { irA, router } from "@/test/navegacion-superficial";

vi.mock("next/navigation", () => import("@/test/navegacion-superficial"));

const { registrarEvento } = vi.hoisted(() => ({ registrarEvento: vi.fn() }));
vi.mock("@/lib/analytics", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/analytics")>()),
  registrarEvento,
}));

const mercado = CONSOLE_SPACES.find((space) => space.key === "mercado")!;
const resumen = CONSOLE_SPACES.find((space) => space.key === "resumen")!;

function query(): URLSearchParams {
  return new URLSearchParams(window.location.search);
}

beforeEach(() => {
  vi.clearAllMocks();
  irA("/mercado");
});
afterEach(() => {
  cleanup();
});

describe("useSpaceView", () => {
  it("entra por la primera vista cuando no hay ?vista=", () => {
    const { result } = renderHook(() => useSpaceView(mercado));
    expect(result.current.view).toBe("tiempo");
  });

  it("respeta la vista pedida si existe en el espacio", () => {
    irA("/mercado?vista=geografia");
    const { result } = renderHook(() => useSpaceView(mercado));
    expect(result.current.view).toBe("geografia");
  });

  it("cae a la primera vista si la pedida no existe", () => {
    // Un `?vista=` inventado no puede dejar el espacio en blanco.
    irA("/mercado?vista=no-existe");
    const { result } = renderHook(() => useSpaceView(mercado));
    expect(result.current.view).toBe("tiempo");
  });

  it("devuelve vista vacía en un espacio sin vistas", () => {
    const { result } = renderHook(() => useSpaceView(resumen));
    expect(result.current.view).toBe("");
  });

  it("cambia de corte sin navegar: la URL y `useSearchParams` llevan la vista, y el ámbito sobrevive", () => {
    irA("/mercado?ccaa=MD&vista=tiempo");
    const entradas = window.history.length;
    const { result } = renderHook(() => useSpaceView(mercado));

    act(() => result.current.setView("organos"));

    // Ni `replace` ni `push` del router: ninguna petición RSC por clic.
    expect(router.replace).not.toHaveBeenCalled();
    expect(router.push).not.toHaveBeenCalled();
    // La URL cambia en su sitio: mismo path, el resto de la query intacto (es
    // lo que mantiene vivo el ámbito) y sin una entrada de historial más.
    expect(window.location.pathname).toBe("/mercado");
    expect(query().get("vista")).toBe("organos");
    expect(query().get("ccaa")).toBe("MD");
    expect(window.history.length).toBe(entradas);
    // Y `useSearchParams` la devuelve: el hook ya está en el corte nuevo.
    expect(result.current.view).toBe("organos");
  });

  it("sigue registrando qué corte se abre", () => {
    const { result } = renderHook(() => useSpaceView(mercado));

    act(() => result.current.setView("cpv"));

    expect(registrarEvento).toHaveBeenCalledWith("espacio_abierto", {
      espacio: "mercado",
      origen: "conmutador",
      vista: "cpv",
    });
  });

  it("parte de la URL viva: no pisa un parámetro escrito justo antes", () => {
    irA("/mercado?vista=tiempo");
    const { result } = renderHook(() => useSpaceView(mercado));

    act(() => {
      // Así escribe `nuqs` el ámbito. En la app Next lo aplica en una
      // transición, y el `useSearchParams` del hook todavía no lo ha visto.
      window.history.replaceState(null, "", "/mercado?vista=tiempo&tecnologia=SAP");
      result.current.setView("cpv");
    });

    expect(query().get("tecnologia")).toBe("SAP");
    expect(query().get("vista")).toBe("cpv");
  });
});

describe("SpaceShell", () => {
  it("pone el nombre del espacio como única cabecera", () => {
    // Las vistas sueltan su `<h1>` propio: repetirlo costaba una banda de cromo.
    render(
      <SpaceShell spaceKey="mercado" view="tiempo">
        <p>contenido</p>
      </SpaceShell>,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Mercado" })).toBeInTheDocument();
    expect(screen.getByText("contenido")).toBeInTheDocument();
  });

  it("pinta una pestaña por vista y marca la activa", () => {
    render(
      <SpaceShell spaceKey="mercado" view="organos">
        <p>contenido</p>
      </SpaceShell>,
    );
    const tabs = screen.getAllByRole("tab");
    // Nueve desde que Renovaciones (el antiguo Horizonte de Mi Pipeline) es un
    // corte más de Mercado. El número sale de la tabla, no de una constante:
    // si alguien añade una vista y no actualiza esto, el fallo lo dice.
    expect(tabs).toHaveLength(SPACE_VIEWS.mercado.length);
    expect(screen.getByRole("tab", { name: "Órganos" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Calendario" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("emite la vista pulsada", () => {
    const onViewChange = vi.fn();
    render(
      <SpaceShell spaceKey="mercado" view="tiempo" onViewChange={onViewChange}>
        <p>contenido</p>
      </SpaceShell>,
    );
    // La pestaña lleva el distintivo "Exp": forma parte de su nombre accesible
    // a propósito — un lector de pantalla también debe saber que la vista
    // está en validación.
    fireEvent.click(screen.getByRole("tab", { name: /Clusters/ }));
    expect(onViewChange).toHaveBeenCalledWith("clusters");
  });

  it("pulsar una pestaña la activa sin navegar: URL → `useSearchParams` → conmutador", () => {
    function Espacio() {
      const { view, setView } = useSpaceView(mercado);
      return (
        <SpaceShell spaceKey="mercado" view={view} onViewChange={setView}>
          <p>vista {view}</p>
        </SpaceShell>
      );
    }
    render(<Espacio />);

    fireEvent.click(screen.getByRole("tab", { name: "CPV" }));

    expect(screen.getByRole("tab", { name: "CPV" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("vista cpv")).toBeInTheDocument();
    expect(query().get("vista")).toBe("cpv");
    expect(router.replace).not.toHaveBeenCalled();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("no revienta si nadie escucha el cambio de vista", () => {
    render(
      <SpaceShell spaceKey="mercado" view="tiempo">
        <p>contenido</p>
      </SpaceShell>,
    );
    expect(() => fireEvent.click(screen.getByRole("tab", { name: "CPV" }))).not.toThrow();
  });

  it("omite el conmutador en un espacio de una sola vista", () => {
    // Una pestaña sola es cromo que no decide nada.
    render(
      <SpaceShell spaceKey="resumen">
        <p>contenido</p>
      </SpaceShell>,
    );
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });

  it("coloca las acciones de la pantalla en la cabecera", () => {
    render(
      <SpaceShell spaceKey="mercado" view="tiempo" actions={<button>Exportar</button>}>
        <p>contenido</p>
      </SpaceShell>,
    );
    expect(screen.getByRole("button", { name: "Exportar" })).toBeInTheDocument();
  });

  it("con bleed la pantalla gobierna su scroll; sin él lo lleva el shell", () => {
    const { container, rerender } = render(
      <SpaceShell spaceKey="mercado" view="tiempo" bleed>
        <p>contenido</p>
      </SpaceShell>,
    );
    const cuerpo = () => container.querySelector("[data-slot=\"space-shell-cuerpo\"]")!;
    expect(cuerpo()).toHaveClass("overflow-hidden");

    rerender(
      <SpaceShell spaceKey="mercado" view="tiempo">
        <p>contenido</p>
      </SpaceShell>,
    );
    expect(cuerpo()).toHaveClass("overflow-y-auto");
  });

  it("sin bleed no hay borde duro: el separador es el borde de scroll, apagado en el tope", () => {
    // apple-design §12: en el tope la cabecera y el cuerpo son la misma
    // superficie y una línea fija anunciaría una profundidad que no existe.
    const { container } = render(
      <SpaceShell spaceKey="mercado" view="tiempo">
        <p>contenido</p>
      </SpaceShell>,
    );
    expect(container.querySelector("header")).not.toHaveClass("border-b");
    expect(container.querySelector("[data-scroll-edge]")).toHaveAttribute("data-scroll-edge", "off");
    // El centinela mide el cuerpo, que es quien scrollea en estas pantallas.
    const cuerpo = container.querySelector("[data-slot=\"space-shell-cuerpo\"]")!;
    expect(cuerpo.firstElementChild).toHaveAttribute("data-scroll-edge-sentinel");
  });

  it("con bleed conserva el borde duro y no monta el de scroll", () => {
    // Con `bleed` el cuerpo no scrollea: no hay nada que el borde de scroll
    // pueda anunciar, y la línea separa la cabecera de la tabla pegada a ella.
    const { container } = render(
      <SpaceShell spaceKey="mercado" view="tiempo" bleed>
        <p>contenido</p>
      </SpaceShell>,
    );
    expect(container.querySelector("header")).toHaveClass("border-b");
    expect(container.querySelector("[data-scroll-edge]")).toBeNull();
    expect(container.querySelector("[data-scroll-edge-sentinel]")).toBeNull();
  });

  it("no revienta con un espacio desconocido", () => {
    render(
      <SpaceShell spaceKey="no-existe">
        <p>contenido</p>
      </SpaceShell>,
    );
    expect(screen.getByText("contenido")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });
});
