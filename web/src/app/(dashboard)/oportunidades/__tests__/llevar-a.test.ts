import { afterEach, describe, expect, it, vi } from "vitest";
import { llevarA } from "../_lib/llevar-a";

/**
 * El salto a un panel de la ficha desplaza solo su contenedor con scroll: con
 * `scrollIntoView` se desplazaba también el documento y la cabecera de la
 * ficha se salía de la pantalla.
 */
function montar() {
  document.body.innerHTML =
    '<div id="scroll" style="overflow-y: auto"><section id="destino" tabindex="-1">panel</section></div>';
  const contenedor = document.getElementById("scroll") as HTMLElement;
  const destino = document.getElementById("destino") as HTMLElement;
  // jsdom no maqueta: se le dan las medidas de un contenedor que desborda.
  Object.defineProperty(contenedor, "scrollHeight", { value: 2000 });
  Object.defineProperty(contenedor, "clientHeight", { value: 600 });
  contenedor.scrollTop = 100;
  contenedor.getBoundingClientRect = () => ({ top: 266 }) as DOMRect;
  destino.getBoundingClientRect = () => ({ top: 866 }) as DOMRect;
  const scrollTo = vi.fn();
  contenedor.scrollTo = scrollTo as typeof contenedor.scrollTo;
  return { destino, scrollTo };
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("llevarA", () => {
  it("desplaza el contenedor hasta el panel, con aire, y le da el foco", () => {
    vi.stubGlobal("matchMedia", () => ({ matches: false }));
    const { destino, scrollTo } = montar();
    const scrollDelDocumento = vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);

    llevarA("destino");

    expect(scrollTo).toHaveBeenCalledWith({ top: 100 + (866 - 266) - 16, behavior: "smooth" });
    expect(document.activeElement).toBe(destino);
    expect(scrollDelDocumento).not.toHaveBeenCalled();
  });

  it("con movimiento reducido salta sin animar", () => {
    vi.stubGlobal("matchMedia", () => ({ matches: true }));
    const { scrollTo } = montar();

    llevarA("destino");

    expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ behavior: "auto" }));
  });

  it("sin el panel en la página no hace nada", () => {
    expect(() => llevarA("no-existe")).not.toThrow();
  });
});
