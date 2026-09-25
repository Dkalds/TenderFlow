/**
 * Esqueletos de ruta de Oportunidades.
 *
 * `oportunidades/loading.tsx` envuelve la página del espacio **y** la ficha
 * (`/oportunidades/[id]`): el prefetch de un enlace a una ficha desde la
 * Agenda o Dirección se detiene en él. Lo que fija este suite es que mira la
 * ruta —el tablero para el espacio, la ficha para cualquier hija— y que la
 * ficha se pinta igual desde los dos `loading.tsx`.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { irA } from "@/test/navegacion-superficial";
import OportunidadesLoading from "../loading";
import OportunidadLoading from "../[id]/loading";

vi.mock("next/navigation", () => import("@/test/navegacion-superficial"));

afterEach(cleanup);

function pieza(container: HTMLElement, slot: string): Element | null {
  return container.querySelector(`[data-slot="${slot}"]`);
}

describe("loading de Oportunidades", () => {
  it("en el espacio pinta su marco con el tablero, que es la vista de entrada", () => {
    irA("/oportunidades");
    const { container } = render(<OportunidadesLoading />);

    expect(pieza(container, "space-shell-esqueleto")).not.toBeNull();
    expect(pieza(container, "tablero-esqueleto")).not.toBeNull();
    expect(pieza(container, "ficha-esqueleto")).toBeNull();
  });

  it("al abrir una ficha pinta la ficha, no un tablero", () => {
    irA("/oportunidades/123");
    const { container } = render(<OportunidadesLoading />);

    expect(pieza(container, "ficha-esqueleto")).not.toBeNull();
    expect(pieza(container, "tablero-esqueleto")).toBeNull();
    expect(pieza(container, "space-shell-esqueleto")).toBeNull();
  });

  it("la ficha es la misma desde el `loading.tsx` del espacio y desde el suyo", () => {
    irA("/oportunidades/123");
    const desdeElEspacio = render(<OportunidadesLoading />).container.innerHTML;
    cleanup();
    const desdeLaFicha = render(<OportunidadLoading />).container.innerHTML;

    expect(desdeElEspacio).toBe(desdeLaFicha);
  });
});
