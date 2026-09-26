/**
 * Tests del marco del dashboard (`components/layout/console-frame.tsx`).
 *
 * Desde la retirada del cromo heredado (2026-08, con los 14 espacios
 * construidos) el marco monta una única superficie: rail + barra de ámbito +
 * shell, sin depender de la ruta. Estos tests fijan que ninguna banda del
 * cromo viejo (KPI bar / breadcrumb / pestañas) reaparezca, que en móvil la
 * barra superior del rail quede encima del contenido y no a su lado, y que el
 * marco mida la pantalla para que `#main-content` se quede con lo que deja el
 * cromo.
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

});

describe("ConsoleFrame — alto", () => {
  // Las pantallas miden `h-full` de `#main-content`, que se queda con lo que
  // deja el cromo. Eso solo vale si el marco mide la pantalla y la columna
  // puede encoger: con alto mínimo, `#main-content` crecía con su contenido,
  // se desplazaba el documento y cada pantalla tenía que restar a mano el cromo
  // que conocía. La franja de primer uso del ámbito no entraba en esa cuenta y
  // alargaba el documento 84px a 1366×768. La medida real, con la franja
  // visible, la cubre `e2e/responsive.spec.ts`.
  const montar = () =>
    render(
      <ConsoleFrame>
        <p>contenido</p>
      </ConsoleFrame>,
    );

  it("el marco mide la pantalla, no un mínimo", () => {
    montar();
    const marco = screen.getByTestId("barra-movil").parentElement!;

    expect(marco).toHaveClass("h-screen");
    expect(marco).not.toHaveClass("min-h-screen");
  });

  it("la columna se queda con lo que deja la barra móvil y encoge por debajo de su contenido", () => {
    // Apilada bajo la barra móvil la columna es un hijo flex del marco en su
    // eje: sin `min-h-0` no bajaría del alto de su contenido, y una página
    // larga estiraría el marco en vez de desplazarse dentro de `#main-content`.
    montar();
    const columna = screen.getByTestId("shell").parentElement!;

    expect(columna).toHaveClass("flex", "flex-col", "flex-1", "min-h-0");
    // Por separado: `not.toHaveClass(a, b)` pasa en cuanto falta una de las dos.
    expect(columna).not.toHaveClass("min-h-screen");
    expect(columna).not.toHaveClass("md:min-h-screen");
  });
});
