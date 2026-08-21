/**
 * Tests del borde de scroll (`components/layout/scroll-edge.tsx`).
 *
 * Lo que fijan: el cromo flotante **no** dibuja un separador cuando el
 * contenido está en el tope, y sí lo dibuja en cuanto algo pasa por debajo. Ese
 * "sólo cuando hay algo debajo" es todo el punto del efecto — con el `border-b`
 * fijo anterior la línea estaba siempre, informara o no.
 *
 * También fijan el contrato de movimiento de `docs/frontend-motion.md`: se
 * anima sólo `opacity`, la entrada es más lenta que la salida, y jamás
 * `transform`/`width`/`height`.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, act } from "@testing-library/react";
import {
  ScrollEdge,
  ScrollEdgeProvider,
  ScrollEdgeSentinel,
  ScrollEdgeUnder,
  useScrollEdgeState,
} from "@/components/layout/scroll-edge";

/**
 * jsdom no trae `IntersectionObserver`. El doble guarda la callback y las
 * opciones para poder disparar la intersección a mano y comprobar contra qué
 * contenedor se observa.
 */
interface Observed {
  callback: IntersectionObserverCallback;
  root: Element | Document | null;
  target: Element | null;
  disconnected: boolean;
}

const observados: Observed[] = [];

class FakeIntersectionObserver {
  private readonly registro: Observed;

  constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
    this.registro = {
      callback,
      root: options?.root ?? null,
      target: null,
      disconnected: false,
    };
    observados.push(this.registro);
  }

  observe(target: Element) {
    this.registro.target = target;
  }

  unobserve() {}

  disconnect() {
    this.registro.disconnected = true;
  }
}

/** Simula que el centinela entra o sale del contenedor con scroll. */
function intersecta(visible: boolean) {
  const ultimo = observados[observados.length - 1];
  act(() => {
    ultimo.callback([{ isIntersecting: visible } as IntersectionObserverEntry], {} as IntersectionObserver);
  });
}

function Cromo() {
  return <ScrollEdge active={useScrollEdgeState()} />;
}

/** El marco mínimo: cromo arriba, centinela dentro del contenedor con scroll. */
function Marco() {
  return (
    <ScrollEdgeProvider>
      <Cromo />
      <main data-testid="scroller">
        <ScrollEdgeSentinel />
        <p>contenido</p>
      </main>
    </ScrollEdgeProvider>
  );
}

const borde = () => document.querySelector("[data-scroll-edge]")!;

beforeEach(() => {
  observados.length = 0;
  vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ScrollEdge — cuándo existe el borde", () => {
  it("no dibuja separador con el contenido en el tope", () => {
    render(<Marco />);
    expect(borde()).toHaveAttribute("data-scroll-edge", "off");
    expect(borde().className).toContain("opacity-0");
  });

  it("lo dibuja en cuanto el centinela sale de vista", () => {
    render(<Marco />);
    intersecta(false);
    expect(borde()).toHaveAttribute("data-scroll-edge", "on");
    expect(borde().className).toContain("opacity-100");
  });

  it("lo retira al volver al tope", () => {
    render(<Marco />);
    intersecta(false);
    intersecta(true);
    expect(borde()).toHaveAttribute("data-scroll-edge", "off");
  });

  it("ningún cromo lleva un borde duro de clase", () => {
    // La regresión que cierra: si alguien devuelve el `border-b`, el separador
    // vuelve a estar siempre y el efecto deja de significar nada.
    render(<Marco />);
    expect(borde().className).not.toContain("border-b");
  });
});

describe("ScrollEdgeSentinel", () => {
  it("observa el contenedor con scroll, no el viewport", () => {
    // Con `root: null` el centinela nunca saldría de vista: el marco scrollea
    // dentro de `<main>`, no en la ventana.
    render(<Marco />);
    const observado = observados[observados.length - 1];
    expect(observado.root).toBe(screen.getByTestId("scroller"));
    expect(observado.target).toBe(document.querySelector("[data-scroll-edge-sentinel]"));
  });

  it("no ocupa espacio: 1px compensado con -1px de margen", () => {
    // Un centinela con alto real crearía 1px de scroll propio en las pantallas
    // que llenan el alto exacto del marco.
    render(<Marco />);
    const sentinel = document.querySelector("[data-scroll-edge-sentinel]")!;
    expect(sentinel.className).toContain("h-px");
    expect(sentinel.className).toContain("-mb-px");
  });

  it("desconecta el observador al desmontar", () => {
    const { unmount } = render(<Marco />);
    unmount();
    expect(observados[observados.length - 1].disconnected).toBe(true);
  });

  it("sin IntersectionObserver no revienta y se queda sin borde", () => {
    // Navegador viejo o entorno sin la API: el estado seguro es "en el tope".
    vi.stubGlobal("IntersectionObserver", undefined);
    expect(() => render(<Marco />)).not.toThrow();
    expect(borde()).toHaveAttribute("data-scroll-edge", "off");
  });
});

describe("ScrollEdge — contrato de movimiento", () => {
  it("anima sólo opacidad", () => {
    render(<Marco />);
    expect(borde().className).toContain("transition-opacity");
    expect(borde().className).not.toContain("transition-all");
    expect(borde().className).not.toContain("translate");
  });

  it("entra en 260ms y sale más rápido, en 170ms", () => {
    render(<Marco />);
    expect(borde().className).toContain("duration-[170ms]");

    intersecta(false);
    expect(borde().className).toContain("duration-[260ms]");
    expect(borde().className).toContain("ease-[cubic-bezier(.21,1.02,.73,1)]");
  });
});

describe("ScrollEdge — variantes de anclaje", () => {
  it("la variante hermana no ocupa alto", () => {
    const { container } = render(<ScrollEdge active={false} />);
    expect(container.firstElementChild!.className).toContain("h-0");
    expect(borde().className).toContain("top-0");
  });

  it("la variante interior cuelga del borde inferior del cromo", () => {
    render(<ScrollEdgeUnder active />);
    expect(borde().className).toContain("top-full");
  });

  it("es invisible para los lectores de pantalla", () => {
    render(<ScrollEdgeUnder active />);
    expect(borde()).toHaveAttribute("aria-hidden", "true");
  });
});

describe("useScrollEdgeState", () => {
  it("sin proveedor no hay borde: un cromo suelto no separa nada", () => {
    render(<Cromo />);
    expect(borde()).toHaveAttribute("data-scroll-edge", "off");
  });
});
