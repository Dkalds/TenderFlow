/**
 * Pestaña «Organización» (S2.1 y S2.2).
 *
 * Lo que se prueba es lo que el plan pide de la UI y el backend no puede
 * garantizar: que la pantalla **marque qué campos faltan** —que es lo que
 * explica por qué el go/no-go dice «desconocido»— y que un `viewer` lea sin
 * que se le ofrezca escribir.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OrganizacionTab } from "../organizacion-tab";

const CAPACIDAD_VACIA = {
  organization_id: 7,
  updated_at: null,
  certificaciones: [],
  facturacion: [],
  referencias: [],
  perfiles_equipo: [],
  campos_incompletos: ["certificaciones", "facturacion", "referencias", "perfiles_equipo"],
};

const CAPACIDAD_PARCIAL = {
  ...CAPACIDAD_VACIA,
  updated_at: "2026-09-06T10:00:00+00:00",
  certificaciones: [{ nombre: "ISO/IEC 27001", ambito: "company", vigente_hasta: "2027-01-01" }],
  campos_incompletos: ["facturacion", "referencias", "perfiles_equipo"],
};

function stubFetch(capacidad: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.endsWith("/capabilities")) {
        return { ok: true, status: 200, json: async () => capacidad };
      }
      if (url.endsWith("/nifs")) {
        return { ok: true, status: 200, json: async () => ({ organization_id: 7, nifs: [] }) };
      }
      throw new Error(`URL no esperada: ${url}`);
    }),
  );
}

function renderTab(props: { canManage: boolean; isPersonal?: boolean }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <OrganizacionTab
        organizationId={7}
        canManage={props.canManage}
        isPersonal={props.isPersonal ?? false}
      />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("OrganizacionTab", () => {
  it("marca las cuatro familias vacías para explicar los «desconocido»", async () => {
    stubFetch(CAPACIDAD_VACIA);
    renderTab({ canManage: true });

    await waitFor(() =>
      expect(screen.getByText(/responderá «desconocido» en estas familias/i)).toBeInTheDocument(),
    );
    // Cada familia aparece dos veces: como aviso de lo que falta y como
    // título de su sección editable.
    for (const familia of [
      "Certificaciones",
      "Facturación anual",
      "Referencias de contratos",
      "Perfiles de equipo",
    ]) {
      expect(screen.getAllByText(familia).length).toBe(2);
    }
  });

  it("deja de marcar una familia en cuanto tiene datos", async () => {
    stubFetch(CAPACIDAD_PARCIAL);
    renderTab({ canManage: true });

    await waitFor(() => expect(screen.getByDisplayValue("ISO/IEC 27001")).toBeInTheDocument());
    // Las certificaciones ya solo salen como título de sección; las otras
    // tres siguen saliendo además como aviso de lo que falta.
    expect(screen.getAllByText("Certificaciones").length).toBe(1);
    expect(screen.getAllByText("Facturación anual").length).toBe(2);
  });

  it("un viewer lee el perfil y no ve el botón de guardar", async () => {
    stubFetch(CAPACIDAD_PARCIAL);
    renderTab({ canManage: false });

    await waitFor(() =>
      expect(screen.getByDisplayValue("ISO/IEC 27001")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: /guardar perfil/i })).not.toBeInTheDocument();
    expect(
      screen.getByText(/Solo el propietario o un administrador pueden cambiar el perfil/i),
    ).toBeInTheDocument();
  });

  it("la organización personal no declara identidad fiscal", () => {
    stubFetch(CAPACIDAD_VACIA);
    renderTab({ canManage: true, isPersonal: true });

    expect(screen.getByText(/no concurre a licitaciones/i)).toBeInTheDocument();
    expect(screen.queryByText("Perfil de capacidad")).not.toBeInTheDocument();
  });
});
