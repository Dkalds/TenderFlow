import { describe, it, expect, afterEach, vi } from "vitest";
import { render } from "@testing-library/react";

// DashboardShell monta `useKeyboardShortcuts`, que necesita el router.
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import { DashboardShell } from "@/components/layout/dashboard-shell";
import { useDensity } from "@/lib/density";

afterEach(() => {
  useDensity.setState({ compact: false });
});

describe("DashboardShell", () => {
  it("exposes the main landmark as a focus target for the skip link", () => {
    // Sin `tabIndex={-1}` el salto mueve el scroll pero no el foco en Safari,
    // así que el teclado seguía atrapado en la barra de navegación.
    const { container } = render(<DashboardShell>contenido</DashboardShell>);
    const main = container.querySelector("main")!;

    expect(main).toHaveAttribute("id", "main-content");
    expect(main).toHaveAttribute("tabindex", "-1");
  });

  it("declares the density so the stylesheet can act on the primitives", () => {
    // Regresión: el toggle aplicaba `[&_.container]:px-2` y la clase
    // `.container` no se usa en ningún componente del proyecto, así que el
    // control existía y no cambiaba nada.
    const { container, rerender } = render(<DashboardShell>contenido</DashboardShell>);
    expect(container.querySelector("main")).toHaveAttribute("data-density", "normal");

    useDensity.setState({ compact: true });
    rerender(<DashboardShell>contenido</DashboardShell>);

    expect(container.querySelector("main")).toHaveAttribute("data-density", "compact");
  });

  it("no longer relies on the unused .container selector", () => {
    useDensity.setState({ compact: true });
    const { container } = render(<DashboardShell>contenido</DashboardShell>);

    expect(container.querySelector("main")!.className).not.toContain("container");
  });
});
