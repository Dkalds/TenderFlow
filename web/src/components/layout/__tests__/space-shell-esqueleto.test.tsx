/**
 * Tests del esqueleto de ruta de un espacio (`space-shell-esqueleto.tsx`).
 *
 * Lo pinta el `loading.tsx` de Mercado y Oportunidades mientras llega el RSC de
 * la ruta, y el relevo con `SpaceShell` sólo es invisible si miden lo mismo. Lo
 * que se puede fijar sin un navegador: las mismas clases de altura y relleno
 * que el shell, el borde duro sólo con `bleed`, y una pestaña por vista de la
 * tabla de la que sale el conmutador.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { SPACE_VIEWS } from "@/lib/space-views";
import { SpaceShell } from "@/components/layout/space-shell";
import { SpaceShellEsqueleto, VistaEsqueleto } from "@/components/layout/space-shell-esqueleto";

vi.mock("next/navigation", () => import("@/test/navegacion-superficial"));

afterEach(cleanup);

function partes(container: HTMLElement) {
  const raiz = container.querySelector('[data-slot="space-shell-esqueleto"]')!;
  return { raiz, cabecera: raiz.firstElementChild!, cuerpo: raiz.lastElementChild! };
}

describe("SpaceShellEsqueleto", () => {
  it("pinta una pestaña por vista del espacio, de la misma tabla que el conmutador", () => {
    const { container } = render(
      <SpaceShellEsqueleto spaceKey="mercado">
        <VistaEsqueleto />
      </SpaceShellEsqueleto>,
    );
    expect(container.querySelectorAll('[data-slot="pestana-esqueleto"]')).toHaveLength(SPACE_VIEWS.mercado.length);
  });

  it("en un espacio sin conmutador no promete pestañas", () => {
    const { container } = render(
      <SpaceShellEsqueleto spaceKey="resumen">
        <p>contenido</p>
      </SpaceShellEsqueleto>,
    );
    expect(container.querySelectorAll('[data-slot="pestana-esqueleto"]')).toHaveLength(0);
  });

  it("mide lo mismo que `SpaceShell`: alto total, cabecera y relleno del cuerpo", () => {
    const shell = render(
      <SpaceShell spaceKey="mercado" view="tiempo">
        <p>contenido</p>
      </SpaceShell>,
    ).container;
    const esqueleto = partes(
      render(
        <SpaceShellEsqueleto spaceKey="mercado">
          <p>contenido</p>
        </SpaceShellEsqueleto>,
      ).container,
    );

    const alto = "h-[calc(100vh-52px)]";
    expect(esqueleto.raiz).toHaveClass(alto);
    expect(Array.from(shell.querySelectorAll("div")).some((nodo) => nodo.classList.contains(alto))).toBe(true);
    for (const clase of ["h-11", "px-4"]) {
      expect(shell.querySelector("header")).toHaveClass(clase);
      expect(esqueleto.cabecera).toHaveClass(clase);
    }
    for (const clase of ["px-4", "pt-4", "pb-6"]) {
      expect(shell.querySelector('[data-slot="space-shell-cuerpo"]')).toHaveClass(clase);
      expect(esqueleto.cuerpo).toHaveClass(clase);
    }
  });

  it("con `bleed`, borde duro y cuerpo sin relleno; sin él, al revés, igual que el shell", () => {
    const { container, rerender } = render(
      <SpaceShellEsqueleto spaceKey="oportunidades" bleed>
        <p>contenido</p>
      </SpaceShellEsqueleto>,
    );
    expect(partes(container).cabecera).toHaveClass("border-b");
    expect(partes(container).cuerpo).not.toHaveClass("px-4");

    rerender(
      <SpaceShellEsqueleto spaceKey="oportunidades">
        <p>contenido</p>
      </SpaceShellEsqueleto>,
    );
    expect(partes(container).cabecera).not.toHaveClass("border-b");
    expect(partes(container).cuerpo).toHaveClass("px-4");
  });
});
