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

  it("al abrir una empresa pinta la ficha, no el marco del espacio", () => {
    irA("/competencia/empresa/7");
    const { container } = render(<CompetenciaLoading />);

    expect(pieza(container, "ficha-empresa-esqueleto")).not.toBeNull();
    expect(pieza(container, "space-shell-esqueleto")).toBeNull();
  });
});
