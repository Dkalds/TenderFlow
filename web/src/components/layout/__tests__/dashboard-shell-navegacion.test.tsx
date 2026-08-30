import { describe, it, expect, afterEach, vi } from "vitest";
import { render } from "@testing-library/react";

/**
 * Anuncio y foco al cambiar de espacio.
 *
 * En un fichero aparte de `dashboard-shell.test.tsx` porque necesita un
 * `usePathname` que cambie entre renders, y aquel lo tiene fijado en `/radar`
 * para todo el módulo.
 */
let rutaActual = "/radar";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => rutaActual,
}));

const anunciar = vi.fn();
vi.mock("@/components/live-region", () => ({
  useAnnounce: () => anunciar,
}));

import { DashboardShell } from "@/components/layout/dashboard-shell";

afterEach(() => {
  anunciar.mockClear();
  rutaActual = "/radar";
});

describe("cambio de pantalla", () => {
  it("no anuncia nada en el primer render", () => {
    // Al entrar, el lector ya está leyendo la página: anunciar aquí duplicaría
    // el título en vez de informar de un cambio.
    render(<DashboardShell>contenido</DashboardShell>);
    expect(anunciar).not.toHaveBeenCalled();
  });

  it("anuncia el nombre del espacio nuevo y lleva el foco al contenido", () => {
    const { container, rerender } = render(<DashboardShell>contenido</DashboardShell>);

    rutaActual = "/mercado";
    rerender(<DashboardShell>contenido</DashboardShell>);

    expect(anunciar).toHaveBeenCalledWith("Mercado");
    expect(document.activeElement).toBe(container.querySelector("main"));
  });

  it("no reanuncia si la ruta no cambia", () => {
    const { rerender } = render(<DashboardShell>contenido</DashboardShell>);
    rerender(<DashboardShell>otro contenido</DashboardShell>);
    expect(anunciar).not.toHaveBeenCalled();
  });
});
