/**
 * Esqueletos de ruta de Competencia.
 *
 * `competencia/loading.tsx` envuelve el espacio **y** la ficha de empresa
 * (`/competencia/empresa/[empresaId]`): el prefetch de un enlace a una empresa
 * desde otro espacio se detiene en él. Lo que fija este suite es que mira la
 * ruta —el marco con la vista para el espacio, la ficha para cualquier hija—.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { irA } from "@/test/navegacion-superficial";
import CompetenciaLoading from "../loading";

vi.mock("next/navigation", () => import("@/test/navegacion-superficial"));

afterEach(cleanup);

function pieza(container: HTMLElement, slot: string): Element | null {
  return container.querySelector(`[data-slot="${slot}"]`);
}

describe("loading de Competencia", () => {
  it("en el espacio pinta su marco, con una pestaña por vista", () => {
    irA("/competencia");
    const { container } = render(<CompetenciaLoading />);

    expect(pieza(container, "space-shell-esqueleto")).not.toBeNull();
    expect(container.querySelectorAll('[data-slot="pestana-esqueleto"]').length).toBeGreaterThan(1);
    expect(pieza(container, "ficha-empresa-esqueleto")).toBeNull();
  });

  it("en Empresas y en Revisión pinta el maestro a sangre, como la vista", () => {
    // Las dos vistas que fueron el espacio Empresas gobiernan su superficie
    // entera: el esqueleto con relleno saltaría al llegar la columna del
    // maestro.
    for (const vista of ["empresas", "revision"]) {
      irA(`/competencia?vista=${vista}`);
      const { container, unmount } = render(<CompetenciaLoading />);
      expect(pieza(container, "space-shell-esqueleto"), vista).not.toBeNull();
      expect(pieza(container, "empresas-esqueleto"), vista).not.toBeNull();
      unmount();
    }
    irA("/competencia?vista=utes");
    const { container } = render(<CompetenciaLoading />);
    expect(pieza(container, "empresas-esqueleto")).toBeNull();
  });

  it("al abrir una empresa pinta la ficha, no el marco del espacio", () => {
    irA("/competencia/empresa/7");
    const { container } = render(<CompetenciaLoading />);

    expect(pieza(container, "ficha-empresa-esqueleto")).not.toBeNull();
    expect(pieza(container, "space-shell-esqueleto")).toBeNull();
  });
});
