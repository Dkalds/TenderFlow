/**
 * Tests del borde de scroll (`components/layout/scroll-edge.tsx`).
 *
 * Lo que fijan: el cromo flotante **no** dibuja un separador cuando el
 * contenido está en el tope, y sí lo dibuja en cuanto algo pasa por debajo. Ese
 * "sólo cuando hay algo debajo" es todo el punto del efecto — con el `border-b`
 * fijo anterior la línea estaba siempre, informara o no.
 *
 * Y contra qué se mide: un cuerpo con scroll propio, contra sí mismo; el marco,
 * cuyo `<main>` crece con el contenido y no desborda, contra el viewport.
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

/**
 * Una pantalla de alto fijo (`SpaceShell`, Resumen): cromo arriba, centinela
 * como primer hijo del cuerpo con scroll.
 */
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

/**
 * El marco del dashboard: se desplaza el documento, así que el centinela va
 * antes del marco y fuera de `<main>`.
 */
function MarcoDelDocumento() {
  return (
    <ScrollEdgeProvider>
      <ScrollEdgeSentinel contenedor="documento" />
      <div data-testid="marco">
        <Cromo />
        <main>
          <p>contenido</p>
        </main>
      </div>
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
  it("por defecto observa a su padre, el cuerpo con scroll, no el viewport", () => {
    // En `SpaceShell` y Resumen el documento no se mueve: se desplaza el cuerpo
    // de la pantalla. Contra el viewport el centinela no saldría nunca de vista.
    render(<Marco />);
    const observado = observados[observados.length - 1];
    expect(observado.root).toBe(screen.getByTestId("scroller"));
    expect(observado.target).toBe(document.querySelector('[data-scroll-edge-sentinel="padre"]'));
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

describe("ScrollEdgeSentinel — contra el documento", () => {
  it("observa el viewport, no a su padre", () => {
    // El `<main>` del marco lleva `overflow-auto`, pero su columna tiene alto
    // mínimo y no fijo: crece con el contenido. Medido a 1440×900 con 3000px de
    // relleno, `scrollHeight === clientHeight` (3512) y el documento desbordaba
    // 2664px. Con `main` de root el centinela no salía nunca de vista, y el
    // borde del marco se quedaba apagado en todas las pantallas.
    render(<MarcoDelDocumento />);
    const observado = observados[observados.length - 1];
    expect(observado.target).toBe(document.querySelector('[data-scroll-edge-sentinel="documento"]'));
    expect(observado.root).toBeNull();
  });

  it("enciende el borde al salir de la ventana y lo apaga al volver al tope", () => {
    render(<MarcoDelDocumento />);
    expect(borde()).toHaveAttribute("data-scroll-edge", "off");

    intersecta(false);
    expect(borde()).toHaveAttribute("data-scroll-edge", "on");

    intersecta(true);
    expect(borde()).toHaveAttribute("data-scroll-edge", "off");
  });

  it("no ocupa espacio antes del marco", () => {
    // Va delante del marco, en flujo: con alto real empujaría el marco 1px y
    // el documento mediría 1px más que la ventana en las pantallas de alto fijo.
    render(<MarcoDelDocumento />);
    const sentinela = document.querySelector('[data-scroll-edge-sentinel="documento"]')!;
    expect(sentinela.nextElementSibling).toBe(screen.getByTestId("marco"));
    expect(sentinela).toHaveClass("h-px", "-mb-px");
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
