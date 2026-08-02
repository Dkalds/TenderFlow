/**
 * Tests del marco del dashboard (`components/layout/console-frame.tsx`).
 *
 * Lo que decide este componente es una sola cosa, pero es la que gobierna toda
 * la migración por lotes: una ruta de consola se queda con dos bandas de cromo
 * (rail + ámbito), y una que aún no se ha rediseñado conserva el KPI bar, el
 * breadcrumb y las pestañas — quitárselos antes de tiempo sería perder
 * navegación real.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { ConsoleFrame } from "@/components/layout/console-frame";

const { pathnameRef } = vi.hoisted(() => ({ pathnameRef: { current: "/resumen" } }));

vi.mock("next/navigation", () => ({
  usePathname: () => pathnameRef.current,
}));

// Los hijos se sustituyen por marcadores: aquí sólo se comprueba qué bandas de
// cromo monta el marco, no lo que cada una pinta por dentro.
vi.mock("@/components/layout/console-rail", () => ({
  ConsoleRail: () => <nav data-testid="rail" />,
}));
vi.mock("@/components/layout/scope-bar", () => ({
  ScopeBar: () => <div data-testid="scope-bar" />,
}));
vi.mock("@/components/layout/breadcrumb", () => ({
  Breadcrumb: () => <div data-testid="breadcrumb" />,
}));
vi.mock("@/components/layout/page-tabs", () => ({
  PageTabs: () => <div data-testid="page-tabs" />,
}));
vi.mock("@/components/layout/kpi-bar", () => ({
  KpiBarConnected: () => <div data-testid="kpi-bar" />,
}));
vi.mock("@/components/layout/dashboard-shell", () => ({
  DashboardShell: ({ children }: { children: React.ReactNode }) => (
    <main data-testid="shell">{children}</main>
  ),
}));

afterEach(() => {
  cleanup();
});

const renderAt = (pathname: string) => {
  pathnameRef.current = pathname;
  return render(
    <ConsoleFrame>
      <p>contenido</p>
    </ConsoleFrame>,
  );
};

describe("ConsoleFrame", () => {
  it("monta rail y barra de ámbito en cualquier ruta", () => {
    // Son las dos bandas que sustituyen a las seis: no dependen de la ruta.
    renderAt("/resumen");
    expect(screen.getByTestId("rail")).toBeInTheDocument();
    expect(screen.getByTestId("scope-bar")).toBeInTheDocument();
    expect(screen.getByText("contenido")).toBeInTheDocument();
  });

  it("en una ruta de consola no pinta el cromo heredado", () => {
    renderAt("/radar");
    expect(screen.queryByTestId("kpi-bar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("breadcrumb")).not.toBeInTheDocument();
    expect(screen.queryByTestId("page-tabs")).not.toBeInTheDocument();
  });

  it("en una ruta heredada conserva KPI bar, breadcrumb y pestañas", () => {
    // `/tendencias` redirige hoy, pero el mecanismo debe seguir vivo por si hay
    // que revertir un espacio sacándolo de BUILT_SPACE_ROUTES.
    renderAt("/tendencias");
    expect(screen.getByTestId("kpi-bar")).toBeInTheDocument();
    expect(screen.getByTestId("breadcrumb")).toBeInTheDocument();
    expect(screen.getByTestId("page-tabs")).toBeInTheDocument();
    expect(screen.getByText("contenido")).toBeInTheDocument();
  });

  it("decide por el primer segmento, no por la URL entera", () => {
    renderAt("/detalle?lic=123");
    expect(screen.queryByTestId("breadcrumb")).not.toBeInTheDocument();

    cleanup();
    renderAt("/oportunidades/p-1");
    expect(screen.queryByTestId("breadcrumb")).not.toBeInTheDocument();
  });
});
