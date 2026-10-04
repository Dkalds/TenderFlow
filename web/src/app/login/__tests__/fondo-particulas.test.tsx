/**
 * El fondo en movimiento de `/login`.
 *
 * Volvió el 2026-10-04 con cuatro condiciones que la primera versión no
 * cumplía o que nadie comprobaba: es decorativo, se puede parar, no se mueve si
 * el sistema pide menos movimiento, y no gasta fotogramas con la pestaña
 * oculta. Lo que se ve —la red en sí— lo juzga un ojo, no un test; aquí se fija
 * lo que la hace aceptable en una pantalla de credenciales.
 *
 * jsdom no pinta canvas ni mide cajas, así que el contexto 2D, el tamaño del
 * lienzo y `requestAnimationFrame` se simulan: los fotogramas se disparan a
 * mano, con la hora que cada caso necesita.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { FondoParticulas } from "@/app/login/_components/fondo-particulas";

const ctx = {
  setTransform: vi.fn(),
  clearRect: vi.fn(),
  beginPath: vi.fn(),
  moveTo: vi.fn(),
  lineTo: vi.fn(),
  stroke: vi.fn(),
  arc: vi.fn(),
  fill: vi.fn(),
  fillStyle: "",
  strokeStyle: "",
  lineWidth: 0,
  globalAlpha: 1,
};

const entorno = {
  reducido: false,
  oculta: false,
  ancho: 1200,
  alto: 800,
  /** Fotogramas pedidos y aún no ejecutados. */
  pendientes: new Map<number, FrameRequestCallback>(),
  alRedimensionar: null as (() => void) | null,
};

/** Ejecuta el fotograma pendiente como si el navegador lo pintara en `ahora`. */
function fotograma(ahora: number) {
  const [[id, pintar]] = [...entorno.pendientes];
  entorno.pendientes.delete(id);
  pintar(ahora);
}

/** Coordenada x de la última partícula pintada. */
const ultimaX = () => ctx.arc.mock.calls.at(-1)?.[0] as number;

beforeEach(() => {
  entorno.reducido = false;
  entorno.oculta = false;
  entorno.ancho = 1200;
  entorno.alto = 800;
  entorno.pendientes.clear();
  entorno.alRedimensionar = null;
  vi.clearAllMocks();

  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(ctx as unknown as CanvasRenderingContext2D);
  vi.spyOn(Element.prototype, "clientWidth", "get").mockImplementation(() => entorno.ancho);
  vi.spyOn(Element.prototype, "clientHeight", "get").mockImplementation(() => entorno.alto);
  vi.spyOn(document, "hidden", "get").mockImplementation(() => entorno.oculta);
  // Todas las partículas nacen iguales —en deriva, en el mismo punto y con la
  // misma velocidad—: lo que se mide es cuánto avanzan, no dónde caen.
  vi.spyOn(Math, "random").mockReturnValue(0.1);

  let siguiente = 0;
  vi.stubGlobal("requestAnimationFrame", (pintar: FrameRequestCallback) => {
    siguiente += 1;
    entorno.pendientes.set(siguiente, pintar);
    return siguiente;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => {
    entorno.pendientes.delete(id);
  });
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(avisar: () => void) {
        entorno.alRedimensionar = avisar;
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  vi.stubGlobal("matchMedia", (consulta: string) => ({
    matches: entorno.reducido,
    media: consulta,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("el lienzo", () => {
  it("es decorativo: ni se anuncia ni intercepta el puntero", () => {
    const { container } = render(<FondoParticulas />);

    const lienzo = container.querySelector("canvas");
    expect(lienzo).toHaveAttribute("aria-hidden", "true");
    expect(lienzo).toHaveClass("pointer-events-none");
  });

  it("pinta la red y sigue pidiendo fotogramas mientras está en marcha", () => {
    render(<FondoParticulas />);

    // 1200 × 800 px a una partícula por cada 14.000 px².
    expect(ctx.arc).toHaveBeenCalledTimes(69);
    expect(entorno.pendientes.size).toBe(1);

    fotograma(0);

    expect(ctx.arc).toHaveBeenCalledTimes(138);
    expect(entorno.pendientes.size).toBe(1);
  });

  it("al desmontarse no deja el bucle vivo", () => {
    const { unmount } = render(<FondoParticulas />);

    unmount();

    expect(entorno.pendientes.size).toBe(0);
  });
});

describe("la pausa", () => {
  it("detiene el bucle, conserva lo pintado y lo reanuda", () => {
    render(<FondoParticulas />);
    fotograma(0);
    const borrados = ctx.clearRect.mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: "Pausar fondo" }));

    expect(entorno.pendientes.size).toBe(0);
    // Parada queda el último fotograma: nadie ha vuelto a limpiar el lienzo.
    expect(ctx.clearRect).toHaveBeenCalledTimes(borrados);

    fireEvent.click(screen.getByRole("button", { name: "Reanudar fondo" }));

    expect(entorno.pendientes.size).toBe(1);
    expect(screen.getByRole("button", { name: "Pausar fondo" })).toBeInTheDocument();
  });

  it("reanudar sigue desde donde estaba, sin dar un salto", () => {
    render(<FondoParticulas />);
    fotograma(0);
    fotograma(1000 / 60);
    const antes = ultimaX();

    fireEvent.click(screen.getByRole("button", { name: "Pausar fondo" }));
    fireEvent.click(screen.getByRole("button", { name: "Reanudar fondo" }));
    // Un minuto después: el primer fotograma tras la pausa avanza un paso, no
    // lo que duró la pausa.
    fotograma(60_000);

    expect(ultimaX() - antes).toBeCloseTo(-0.28 * 0.46, 6);
  });
});

describe("cuando no debe moverse", () => {
  it("con «reducir movimiento» pinta un fotograma, no arranca y no ofrece pausa", () => {
    entorno.reducido = true;
    render(<FondoParticulas />);

    expect(ctx.arc).toHaveBeenCalledTimes(69);
    expect(entorno.pendientes.size).toBe(0);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("con la pestaña oculta el bucle se detiene, y vuelve al volver", () => {
    render(<FondoParticulas />);

    entorno.oculta = true;
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(entorno.pendientes.size).toBe(0);

    entorno.oculta = false;
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(entorno.pendientes.size).toBe(1);
  });
});

describe("el paso del tiempo", () => {
  /** Posición de una partícula tras un segundo a `hz` fotogramas por segundo. */
  function trasUnSegundo(hz: number): number {
    const { unmount } = render(<FondoParticulas />);
    for (let i = 0; i <= hz; i++) fotograma((i * 1000) / hz);
    const x = ultimaX();
    unmount();
    return x;
  }

  it("la red va a la misma velocidad a 60 Hz que a 120 Hz", () => {
    // Avanzaba un paso fijo por fotograma: en una pantalla de 120 Hz iba el
    // doble de rápido.
    const a60 = trasUnSegundo(60);
    const a120 = trasUnSegundo(120);

    expect(a60).not.toBe(120); // se ha movido de donde nació
    expect(a120).toBeCloseTo(a60, 6);
  });
});

describe("al cambiar de tamaño", () => {
  it("reparte las partículas que ya había en vez de crearlas otra vez", () => {
    // Con el bucle parado, para que lo único que mueva una partícula sea el
    // cambio de tamaño.
    entorno.reducido = true;
    render(<FondoParticulas />);
    expect(ultimaX()).toBe(120); // 0,1 × 1200
    const nacidas = vi.mocked(Math.random).mock.calls.length;

    entorno.ancho = 600;
    act(() => entorno.alRedimensionar?.());

    // A la mitad de ancho, la mitad de x; y como caben menos, no nace ninguna.
    expect(ultimaX()).toBe(60);
    expect(Math.random).toHaveBeenCalledTimes(nacidas);
    expect(ctx.arc).toHaveBeenCalledTimes(69 + 36);
  });
});
