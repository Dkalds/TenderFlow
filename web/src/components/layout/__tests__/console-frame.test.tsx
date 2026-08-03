/**
 * Tests del marco del dashboard (`components/layout/console-frame.tsx`).
 *
 * Desde la retirada del cromo heredado (2026-08, con los 14 espacios
 * construidos) el marco monta una única superficie: rail + barra de ámbito +
 * shell, sin depender de la ruta. Estos tests fijan que ninguna banda del
 * cromo viejo (KPI bar / breadcrumb / pestañas) reaparezca.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { ConsoleFrame } from "@/components/layout/console-frame";

// Los hijos se sustituyen por marcadores: aquí sólo se comprueba qué bandas de
// cromo monta el marco, no lo que cada una pinta por dentro.
vi.mock("@/components/layout/console-rail", () => ({
  ConsoleRail: () => <nav data-testid="rail" />,
}));
vi.mock("@/components/layout/scope-bar", () => ({
  ScopeBar: () => <div data-testid="scope-bar" />,
}));
vi.mock("@/components/layout/dashboard-shell", () => ({
  DashboardShell: ({ children }: { children: React.ReactNode }) => (
    <main data-testid="shell">{children}</main>
  ),
}));

afterEach(() => {
  cleanup();
});

describe("ConsoleFrame", () => {
  it("monta rail, barra de ámbito y shell — la superficie única", () => {
    render(
      <ConsoleFrame>
        <p>contenido</p>
      </ConsoleFrame>,
    );
    expect(screen.getByTestId("rail")).toBeInTheDocument();
    expect(screen.getByTestId("scope-bar")).toBeInTheDocument();
    expect(screen.getByTestId("shell")).toBeInTheDocument();
    expect(screen.getByText("contenido")).toBeInTheDocument();
  });

  it("no pinta ninguna banda del cromo heredado", () => {
    render(
      <ConsoleFrame>
        <p>contenido</p>
      </ConsoleFrame>,
    );
    expect(screen.queryByTestId("kpi-bar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("breadcrumb")).not.toBeInTheDocument();
    expect(screen.queryByTestId("page-tabs")).not.toBeInTheDocument();
  });
});
