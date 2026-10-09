import * as React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

/**
 * `TooltipProvider` lo monta el layout del dashboard y no la pila común de
 * `SuperficiePrivada` (así `/login` y `/restablecer-contrasena` no cargan Radix
 * Tooltip; ver `components/providers.tsx`). Lo que fija este test es la otra
 * mitad de ese trato: todo lo que pinta el dashboard sigue teniendo el
 * provider. Radix lanza al renderizar un `<Tooltip>` sin él, así que quitarlo
 * de aquí rompería cada pantalla con una pista.
 */

vi.mock("@/components/layout/superficie-privada", () => ({
  SuperficiePrivada: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/connection-banner", () => ({ ConnectionBanner: () => null }));
vi.mock("@/components/layout/console-frame", () => ({
  ConsoleFrame: ({ children }: { children: React.ReactNode }) => <main>{children}</main>,
}));
vi.mock("@/components/oauth-login-telemetry", () => ({ OAuthLoginTelemetry: () => null }));
// Los overlays (paleta, copiloto…) también pintan tooltips: van dentro.
vi.mock("@/components/layout/overlays-dashboard", () => ({
  OverlaysDashboard: () => <Pista texto="overlay" />,
}));

import DashboardLayout from "@/app/(dashboard)/layout";
import { Tooltip, TooltipTrigger } from "@/components/ui/tooltip";

function Pista({ texto }: { texto: string }) {
  return (
    <Tooltip>
      <TooltipTrigger>{texto}</TooltipTrigger>
    </Tooltip>
  );
}

describe("layout del dashboard", () => {
  it("da TooltipProvider a las pantallas y a los overlays", () => {
    render(
      <DashboardLayout>
        <Pista texto="pantalla" />
      </DashboardLayout>,
    );

    expect(screen.getByRole("button", { name: "pantalla" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "overlay" })).toBeInTheDocument();
  });
});
