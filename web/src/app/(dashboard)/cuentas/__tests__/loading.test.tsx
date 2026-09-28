/**
 * Esqueletos de ruta de Cuentas.
 *
 * `cuentas/loading.tsx` envuelve la página del espacio **y** la ficha
 * (`/cuentas/[id]`): el prefetch de un enlace a una cuenta desde otro espacio
 * se detiene en él. Lo que fija este suite es que mira la ruta —el marco con
 * la lista para el espacio, la ficha para cualquier hija—.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { irA } from "@/test/navegacion-superficial";
import CuentasLoading from "../loading";

vi.mock("next/navigation", () => import("@/test/navegacion-superficial"));

afterEach(cleanup);

function pieza(container: HTMLElement, slot: string): Element | null {
  return container.querySelector(`[data-slot="${slot}"]`);
}

describe("loading de Cuentas", () => {
  it("en el espacio pinta su marco con la lista", () => {
    irA("/cuentas");
    const { container } = render(<CuentasLoading />);

    expect(pieza(container, "space-shell-esqueleto")).not.toBeNull();
    expect(pieza(container, "lista-cuentas-esqueleto")).not.toBeNull();
    expect(pieza(container, "ficha-cuenta-esqueleto")).toBeNull();
  });

  it("al abrir una cuenta pinta la ficha, no el marco del espacio", () => {
    irA("/cuentas/12");
    const { container } = render(<CuentasLoading />);

    expect(pieza(container, "ficha-cuenta-esqueleto")).not.toBeNull();
    expect(pieza(container, "space-shell-esqueleto")).toBeNull();
  });
});
