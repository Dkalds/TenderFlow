import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

vi.mock("next/navigation", () => import("@/test/navegacion-superficial"));

import { AvisoCambiosSinGuardar } from "@/components/aviso-cambios-sin-guardar";
import { irA, router } from "@/test/navegacion-superficial";

/**
 * Salir con cambios sin guardar por un enlace de la consola no recarga la
 * página, así que el `beforeunload` del navegador no salta: la pantalla se
 * desmontaba con lo tecleado dentro. Lo que se fija es que ese clic se pare a
 * preguntar, y que no se pare ninguno de los que no pierden nada.
 */

function renderConEnlaces(activo: boolean) {
  irA("/mi-perfil");
  return render(
    <>
      <AvisoCambiosSinGuardar activo={activo} />
      <a href="/radar?tecnologia=SAP">Radar</a>
      <a href="/mi-perfil?vista=otra">Otra vista</a>
      <a href="https://example.test/fuera">Fuera</a>
      <a href="/radar" target="_blank" rel="noreferrer">
        En otra pestaña
      </a>
    </>,
  );
}

/**
 * Pulsa el enlace y devuelve si el aviso canceló la navegación.
 *
 * El oyente de burbujeo apunta el veredicto y cancela él mismo lo que quede:
 * jsdom no navega, y sin eso cada clic que el aviso deja pasar escribe un
 * «Not implemented: navigation» en la salida.
 */
function pulsar(nombre: string, init: MouseEventInit = {}): boolean {
  let cancelado = false;
  const alFinal = (evento: Event) => {
    cancelado = evento.defaultPrevented;
    evento.preventDefault();
  };
  document.addEventListener("click", alFinal);
  fireEvent.click(screen.getByRole("link", { name: nombre }), { button: 0, ...init });
  document.removeEventListener("click", alFinal);
  return cancelado;
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AvisoCambiosSinGuardar", () => {
  it("con cambios, un enlace a otra pantalla se para a preguntar", () => {
    renderConEnlaces(true);

    expect(pulsar("Radar")).toBe(true);

    expect(screen.getByRole("dialog", { name: "Tienes cambios sin guardar" })).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("«Seguir editando» cierra la pregunta y no navega", () => {
    renderConEnlaces(true);
    pulsar("Radar");

    fireEvent.click(screen.getByRole("button", { name: "Seguir editando" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("«Salir sin guardar» va adonde apuntaba el enlace, con su query", () => {
    renderConEnlaces(true);
    pulsar("Radar");

    fireEvent.click(screen.getByRole("button", { name: "Salir sin guardar" }));

    expect(router.push).toHaveBeenCalledWith("/radar?tecnologia=SAP");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("sin cambios no se mete en ningún clic", () => {
    renderConEnlaces(false);

    expect(pulsar("Radar")).toBe(false);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("no pregunta por lo que no desmonta el formulario ni por lo que abre otra pestaña", () => {
    renderConEnlaces(true);

    // Otra vista de la misma pantalla.
    expect(pulsar("Otra vista")).toBe(false);
    // Otra pestaña: por atributo o por tecla.
    expect(pulsar("En otra pestaña")).toBe(false);
    expect(pulsar("Radar", { ctrlKey: true })).toBe(false);
    expect(pulsar("Radar", { metaKey: true })).toBe(false);
    // Fuera de la consola hay recarga: de esa avisa el navegador.
    expect(pulsar("Fuera")).toBe(false);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("con cambios pide confirmación al cerrar o recargar la pestaña, y sin ellos no", () => {
    const { rerender } = render(<AvisoCambiosSinGuardar activo />);
    const conCambios = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(conCambios);
    expect(conCambios.defaultPrevented).toBe(true);

    rerender(<AvisoCambiosSinGuardar activo={false} />);
    const sinCambios = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(sinCambios);
    expect(sinCambios.defaultPrevented).toBe(false);
  });
});
