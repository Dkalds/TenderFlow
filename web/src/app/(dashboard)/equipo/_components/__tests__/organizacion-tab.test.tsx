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

/** Lo que piden las dos tarjetas que valen para cualquier organización. */
function respuestaComun(url: string) {
  if (url.endsWith("/settings")) {
    return {
      ok: true,
      status: 200,
      json: async () => ({ organization_id: 7, tecnologias: ["SAP"], tecnologias_disponibles: ["ORACLE", "SAP"] }),
    };
  }
  if (url.endsWith("/report-schedule")) {
    return {
      ok: true,
      status: 200,
      json: async () => ({
        organization_id: 7,
        tipo: "pipeline_semanal",
        activo: false,
        dia_semana: 0,
        hora_utc: 7,
        destinatarios: null,
      }),
    };
  }
  return null;
}

function stubFetch(capacidad: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const comun = respuestaComun(url);
      if (comun) return comun;
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

  it("con la lectura caída no afirma huecos ni NIFs que no ha leído", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const comun = respuestaComun(url);
        if (comun) return comun;
        if (url.endsWith("/capabilities") || url.endsWith("/nifs")) {
          return new Response(JSON.stringify({ detail: "boom" }), {
            status: 500,
            headers: { "Content-Type": "application/json" },
          });
        }
        throw new Error(`URL no esperada: ${url}`);
      }),
    );
    renderTab({ canManage: true });

    expect(await screen.findByText("No se pudo cargar el perfil de capacidad")).toBeInTheDocument();
    expect(await screen.findByText("No se pudo cargar la identidad fiscal")).toBeInTheDocument();
    // Ni el aviso de familias vacías ni la invitación a declarar el primer NIF:
    // las dos cosas serían la lectura contraria de un fallo.
    expect(screen.queryByText(/responderá «desconocido»/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Todavía no hay ningún NIF declarado/)).not.toBeInTheDocument();
  });

  it("la organización personal no declara identidad fiscal", () => {
    stubFetch(CAPACIDAD_VACIA);
    renderTab({ canManage: true, isPersonal: true });

    expect(screen.getByText(/no concurre a licitaciones/i)).toBeInTheDocument();
    expect(screen.queryByText("Perfil de capacidad")).not.toBeInTheDocument();
  });

  it("la organización personal sí elige tecnologías y programa su informe", async () => {
    // Las dos acotan o resumen el Radar de quien trabaja solo: al sacarlas de
    // Mi perfil no pueden quedar detrás del aviso de «no concurre».
    stubFetch(CAPACIDAD_VACIA);
    renderTab({ canManage: true, isPersonal: true });

    expect(await screen.findByRole("checkbox", { name: "SAP" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "ORACLE" })).not.toBeChecked();
    expect(await screen.findByRole("button", { name: /Guardar programación/ })).toBeInTheDocument();
  });

  it("quien no gestiona la organización ve las tecnologías sin poder cambiarlas", async () => {
    stubFetch(CAPACIDAD_PARCIAL);
    renderTab({ canManage: false });

    expect(await screen.findByRole("checkbox", { name: "SAP" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Guardar tecnologías" })).not.toBeInTheDocument();
    // El informe es de Dirección: ni se enseña ni se pide.
    expect(screen.queryByText("Informe semanal por correo")).not.toBeInTheDocument();
  });
});
