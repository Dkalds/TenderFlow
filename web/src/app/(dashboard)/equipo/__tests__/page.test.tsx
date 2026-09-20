/**
 * `/equipo` monta los webhooks del equipo (cola de S4.2).
 *
 * `WebhooksEquipoView` existía, con alta, ping e historial, y ninguna pantalla
 * la montaba: los webhooks salieron de `/ops` y no llegaron a ningún sitio. Lo
 * que fija este suite es el reparto de permisos de la pestaña: la ven `owner` y
 * `admin`, y un `member` ni siquiera ve el disparador.
 */
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const { organizaciones } = vi.hoisted(() => ({
  organizaciones: {
    data: [] as { id: number; name: string; role: string; is_personal: boolean }[],
  },
}));

vi.mock("@/hooks/use-organization", () => ({
  useOrganizations: () => organizaciones,
  useActiveOrganizationId: () => 21,
  useOrganizationStore: (selector: (state: { setActiveOrganizationId: () => void }) => unknown) =>
    selector({ setActiveOrganizationId: vi.fn() }),
}));
vi.mock("@/components/layout/space-shell", () => ({
  SpaceShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("../_components/crear-organizacion-form", () => ({ CrearOrganizacionForm: () => null }));
vi.mock("../_components/invitaciones-pendientes", () => ({ InvitacionesPendientes: () => null }));
vi.mock("../_components/matriz-permisos", () => ({ MatrizPermisos: () => null }));
vi.mock("../_components/miembros-card", () => ({ MiembrosCard: () => <p>miembros</p> }));
vi.mock("../_components/organizacion-tab", () => ({ OrganizacionTab: () => null }));
vi.mock("../../ops/_components/webhooks-view", () => ({
  WebhooksEquipoView: () => <p>webhooks del equipo</p>,
}));
vi.mock("../../direccion/_components/actividad-equipo", () => ({
  ActividadEquipo: ({ organizationId }: { organizationId: number | null }) => (
    <p>feed de la organización {organizationId}</p>
  ),
}));

import EquipoPage from "@/app/(dashboard)/equipo/page";

function fijarRol(role: string) {
  organizaciones.data = [{ id: 21, name: "Equipo SAP", role, is_personal: false }];
}

afterEach(() => {
  cleanup();
  organizaciones.data = [];
});

describe("EquipoPage — pestaña Integraciones", () => {
  it.each(["owner", "admin"])("un %s ve la pestaña y monta los webhooks del equipo", (role) => {
    fijarRol(role);
    render(<EquipoPage />);

    const pestana = screen.getByRole("tab", { name: "Integraciones" });
    // Radix activa la pestaña en `mousedown`, no en `click`.
    fireEvent.mouseDown(pestana);
    expect(screen.getByText("webhooks del equipo")).toBeInTheDocument();
  });

  it.each(["member", "viewer"])("un %s no ve la pestaña", (role) => {
    fijarRol(role);
    render(<EquipoPage />);

    expect(screen.queryByRole("tab", { name: "Integraciones" })).not.toBeInTheDocument();
    expect(screen.queryByText("webhooks del equipo")).not.toBeInTheDocument();
  });
});

describe("EquipoPage — pestaña Actividad (F4.5)", () => {
  // Un `member` también: el feed vivía sólo en Dirección (owner/admin) y el
  // backend ya lo acota por rol, así que la pantalla no tiene nada que ocultar.
  it.each(["owner", "admin", "member"])("un %s ve el feed de la organización activa", (role) => {
    fijarRol(role);
    render(<EquipoPage />);

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Actividad" }));
    expect(screen.getByText("feed de la organización 21")).toBeInTheDocument();
  });
});
