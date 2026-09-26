/**
 * Tests del marco del dashboard (`components/layout/console-frame.tsx`).
 *
 * Desde la retirada del cromo heredado (2026-08, con los 14 espacios
 * construidos) el marco monta una única superficie: rail + barra de ámbito +
 * shell, sin depender de la ruta. Estos tests fijan que ninguna banda del
 * cromo viejo (KPI bar / breadcrumb / pestañas) reaparezca, y que en móvil la
 * barra superior del rail quede encima del contenido y no a su lado.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { ConsoleFrame } from "@/components/layout/console-frame";

// Los hijos se sustituyen por marcadores: aquí sólo se comprueba qué bandas de
// cromo monta el marco, no lo que cada una pinta por dentro. El rail, como el
// real, devuelve dos hermanos —el de escritorio y la barra superior móvil—:
// dónde cae esa barra respecto al contenido es justo lo que decide el marco.
vi.mock("@/components/layout/console-rail", () => ({
  ConsoleRail: () => (
    <>
      <nav data-testid="rail" />
      <div data-testid="barra-movil" />
    </>
  ),
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

describe("ConsoleFrame — móvil", () => {
  // jsdom no aplica media queries ni calcula cajas: lo que se fija es el
  // contrato de clases. La medida real (375×812: `main` en x=0 con todo el
  // ancho) es de navegador: la cubre `e2e/responsive.spec.ts`.
  const montar = () =>
    render(
      <ConsoleFrame>
        <p>contenido</p>
      </ConsoleFrame>,
    );

  it("apila la barra superior encima del contenido, no a su lado", () => {
    // La barra móvil y la columna del contenido son hermanas en el contenedor
    // del marco. Con ese contenedor en fila a todos los anchos, a 375px la barra
    // se quedaba con 181px a la izquierda y la pantalla con los 194 restantes.
    montar();
    const contenedor = screen.getByTestId("barra-movil").parentElement!;
    const columna = screen.getByTestId("shell").parentElement!;

    expect(columna.parentElement).toBe(contenedor);
    expect(contenedor).toHaveClass("flex", "flex-col", "md:flex-row");
    expect(contenedor).not.toHaveClass("flex-row");
  });

  it("reserva el alto de pantalla a la columna sólo en fila", () => {
    // En columna la barra móvil ya ocupa sus 48px encima: con `min-h-screen`
    // también aquí, el documento mediría siempre 48px más que la ventana.
    montar();
    const columna = screen.getByTestId("shell").parentElement!;

    expect(columna).toHaveClass("flex-1", "md:min-h-screen");
    expect(columna).not.toHaveClass("min-h-screen");
  });

  it("publica el alto del cromo que las pantallas descuentan de la ventana", () => {
    // Las pantallas de alto fijo miden `calc(100vh - var(--alto-cromo))`. Sin
    // la variable, ese `calc` es inválido y su alto cae a `auto`; con 52px
    // también en móvil, desbordarían los 48px de la barra superior.
    montar();
    const contenedor = screen.getByTestId("barra-movil").parentElement!;

    expect(contenedor).toHaveClass("[--alto-cromo:calc(3rem+52px)]", "md:[--alto-cromo:52px]");
  });
});
