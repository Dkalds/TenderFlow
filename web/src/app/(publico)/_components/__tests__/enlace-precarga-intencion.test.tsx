import type { AnchorHTMLAttributes, ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { EnlacePrecargaIntencion } from "../enlace-precarga-intencion";

/**
 * Lo que se fija es el valor de `prefetch` que recibe `next/link`, porque es lo
 * único que decide si Next precarga la ficha: en el DOM no deja rastro. Por eso
 * se sustituye el `Link` por un ancla que lo expone en un atributo.
 */
vi.mock("next/link", () => ({
  default: ({
    prefetch,
    children,
    ...resto
  }: { prefetch?: boolean | null; children?: ReactNode } & AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a data-prefetch={prefetch === null ? "auto" : String(prefetch)} {...resto}>
      {children}
    </a>
  ),
}));

function enlace() {
  return screen.getByRole("link", { name: "Ficha" });
}

describe("EnlacePrecargaIntencion", () => {
  it("no precarga la ficha solo por entrar en pantalla", () => {
    render(<EnlacePrecargaIntencion href="/licitaciones/madrid/ficha/abc">Ficha</EnlacePrecargaIntencion>);

    expect(enlace()).toHaveAttribute("data-prefetch", "false");
    expect(enlace()).toHaveAttribute("href", "/licitaciones/madrid/ficha/abc");
  });

  it.each([
    ["el puntero", (el: HTMLElement) => fireEvent.mouseEnter(el)],
    ["el foco de teclado", (el: HTMLElement) => fireEvent.focus(el)],
    ["el primer toque", (el: HTMLElement) => fireEvent.touchStart(el)],
  ])("vuelve a la precarga por defecto de Next con %s", (_nombre, mostrarIntencion) => {
    render(<EnlacePrecargaIntencion href="/licitaciones/madrid/ficha/abc">Ficha</EnlacePrecargaIntencion>);

    mostrarIntencion(enlace());

    expect(enlace()).toHaveAttribute("data-prefetch", "auto");
  });

  it("conserva los manejadores que le pasa quien lo usa", () => {
    const alPasar = vi.fn();
    const alEnfocar = vi.fn();
    render(
      <EnlacePrecargaIntencion href="/x" onMouseEnter={alPasar} onFocus={alEnfocar}>
        Ficha
      </EnlacePrecargaIntencion>,
    );

    fireEvent.mouseEnter(enlace());
    fireEvent.focus(enlace());

    expect(alPasar).toHaveBeenCalledTimes(1);
    expect(alEnfocar).toHaveBeenCalledTimes(1);
  });
});
