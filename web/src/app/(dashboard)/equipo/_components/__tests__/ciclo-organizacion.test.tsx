/**
 * Equipo › Organización: salir, traspasar y borrar (CU-26).
 *
 * Los cuatro endpoints existían (C2.2) sin ninguna pantalla: quien quería irse
 * de un equipo, o cerrarlo, no tenía cómo. Lo que fija este suite: cada rol ve
 * solo lo que puede hacer, borrar enseña antes lo que se lleva y exige teclear
 * el nombre, y cuando la API se niega se dice su motivo.
 */
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/auth", () => ({
  useSession: () => ({ user: { user_id: "1", email: "dora@example.com" }, isLoading: false }),
}));

import { type Organization, useOrganizationStore } from "@/hooks/use-organization";
import { CicloOrganizacion } from "../ciclo-organizacion";

const ACME: Organization = {
  id: 7,
  name: "Acme Consultores",
  role: "owner",
  is_personal: false,
  created_at: "2026-01-01",
};
const MIEMBROS = [
  { organization_id: 7, user_id: 1, role: "owner", status: "active", display_name: "Dora", email: "dora@example.com" },
  { organization_id: 7, user_id: 2, role: "admin", status: "active", display_name: "Sara", email: "sara@example.com" },
  { organization_id: 7, user_id: 3, role: "member", status: "revoked", display_name: "Rita", email: "rita@example.com" },
].map((m) => ({ ...m, created_at: "2026-01-01", updated_at: "2026-01-01" }));

type Respuesta = { status: number; body: unknown };
let respuestas: Record<string, Respuesta>;
const fetchMock = vi.fn();

function urlDe(entrada: unknown): string {
  return (entrada instanceof Request ? entrada.url : String(entrada)).replace(/^https?:\/\/[^/]+/, "");
}
function metodoDe(entrada: unknown, init?: RequestInit): string {
  return entrada instanceof Request ? entrada.method : (init?.method ?? "GET");
}
function llamada(metodo: string, ruta: string) {
  return fetchMock.mock.calls.find(
    ([entrada, init]) => metodoDe(entrada, init as RequestInit) === metodo && urlDe(entrada) === ruta,
  );
}

function renderCiclo(organizacion = ACME) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CicloOrganizacion organizacion={organizacion} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useOrganizationStore.setState({ activeOrganizationId: 7 });
  respuestas = {
    "GET /api/v1/organizations/7/members": { status: 200, body: MIEMBROS },
    "GET /api/v1/organizations/7/deletion-preview": {
      status: 200,
      body: { oportunidades: 14, comentarios: 37, miembros: 2, adjuntos: -1 },
    },
    "POST /api/v1/organizations/7/leave": { status: 200, body: { status: "ok" } },
    "POST /api/v1/organizations/7/transfer-ownership": { status: 200, body: { status: "ok" } },
    "POST /api/v1/organizations/7/delete": {
      status: 200,
      body: { oportunidades: 14, comentarios: 37, miembros: 2, adjuntos: 0 },
    },
  };
  fetchMock.mockImplementation((entrada: unknown, init?: RequestInit) => {
    const r = respuestas[`${metodoDe(entrada, init)} ${urlDe(entrada)}`] ?? { status: 404, body: {} };
    return Promise.resolve(
      new Response(JSON.stringify(r.body), { status: r.status, headers: { "Content-Type": "application/json" } }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("Ciclo de la organización: lo que ve cada rol", () => {
  it("la organización personal no ofrece nada: ni se sale, ni se traspasa, ni se borra", () => {
    const { container } = renderCiclo({ ...ACME, is_personal: true });
    expect(container).toBeEmptyDOMElement();
  });

  it("un miembro solo puede salir", () => {
    renderCiclo({ ...ACME, role: "member" });
    expect(screen.getByRole("button", { name: /Salir de Acme Consultores/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Traspasar/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Borrar/ })).not.toBeInTheDocument();
  });

  it("la propietaria no ve «salir»: se le dice qué hacer antes", () => {
    renderCiclo();
    expect(screen.queryByRole("button", { name: /Salir de/ })).not.toBeInTheDocument();
    expect(screen.getByText(/traspasa la propiedad antes de salir/)).toBeInTheDocument();
  });
});

describe("Salir", () => {
  it("pide confirmación, sale y deja de tener esa organización activa", async () => {
    renderCiclo({ ...ACME, role: "member" });
    fireEvent.click(screen.getByRole("button", { name: /Salir de Acme Consultores/ }));
    const dialogo = await screen.findByRole("dialog");
    fireEvent.click(within(dialogo).getByRole("button", { name: "Salir" }));

    await waitFor(() => expect(llamada("POST", "/api/v1/organizations/7/leave")).toBeDefined());
    await waitFor(() => expect(useOrganizationStore.getState().activeOrganizationId).toBeNull());
  });

  it("si la API se niega, enseña su motivo en el diálogo", async () => {
    respuestas["POST /api/v1/organizations/7/leave"] = {
      status: 409,
      body: { detail: "Eres el propietario: traspasa la propiedad a otro miembro antes de salir, o borra la organización." },
    };
    renderCiclo({ ...ACME, role: "admin" });
    fireEvent.click(screen.getByRole("button", { name: /Salir de Acme Consultores/ }));
    const dialogo = await screen.findByRole("dialog");
    fireEvent.click(within(dialogo).getByRole("button", { name: "Salir" }));

    expect(await within(dialogo).findByText(/Eres el propietario/)).toBeInTheDocument();
    expect(useOrganizationStore.getState().activeOrganizationId).toBe(7);
  });
});

describe("Traspasar", () => {
  it("solo ofrece miembros activos que no son quien mira, y confirma antes", async () => {
    renderCiclo();
    const selector = await screen.findByLabelText("Nuevo propietario");
    const opciones = within(selector).getAllByRole("option").map((o) => o.textContent);
    expect(opciones).toEqual(["Elige a alguien", "Sara · sara@example.com"]);

    fireEvent.change(selector, { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Traspasar…" }));
    const dialogo = await screen.findByRole("dialog");
    expect(within(dialogo).getByText(/quedarás como administrador/)).toBeInTheDocument();
    fireEvent.click(within(dialogo).getByRole("button", { name: "Traspasar la propiedad" }));

    await waitFor(() => expect(llamada("POST", "/api/v1/organizations/7/transfer-ownership")).toBeDefined());
    const [, init] = llamada("POST", "/api/v1/organizations/7/transfer-ownership")!;
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({ nuevo_owner_user_id: 2 });
  });
});

describe("Borrar", () => {
  it("enseña lo que se lleva, y solo borra tras teclear el nombre", async () => {
    renderCiclo();
    fireEvent.click(screen.getByRole("button", { name: "Borrar la organización…" }));
    const dialogo = await screen.findByRole("dialog");

    expect(await within(dialogo).findByText("14 oportunidades")).toBeInTheDocument();
    expect(within(dialogo).getByText("37 comentarios")).toBeInTheDocument();
    // Un -1 es «no se pudo contar», nunca cero.
    expect(within(dialogo).getByText(/adjuntos: no se pudieron contar/)).toBeInTheDocument();

    const borrar = within(dialogo).getByRole("button", { name: "Borrar definitivamente" });
    expect(borrar).toBeDisabled();
    fireEvent.change(within(dialogo).getByLabelText(/para confirmar/), { target: { value: "Acme" } });
    expect(borrar).toBeDisabled();
    fireEvent.change(within(dialogo).getByLabelText(/para confirmar/), { target: { value: "Acme Consultores" } });
    fireEvent.click(borrar);

    await waitFor(() => expect(llamada("POST", "/api/v1/organizations/7/delete")).toBeDefined());
    const [, init] = llamada("POST", "/api/v1/organizations/7/delete")!;
    // La API pide su palabra fija; el nombre es la confirmación de la persona.
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({ confirmacion: "BORRAR" });
    await waitFor(() => expect(useOrganizationStore.getState().activeOrganizationId).toBeNull());
  });

  it("con la sesión antigua ofrece volver a entrar", async () => {
    respuestas["POST /api/v1/organizations/7/delete"] = {
      status: 403,
      body: { type: "https://licitaciones-sap/errors/reauthentication-required", detail: "Reauthenticate" },
    };
    renderCiclo();
    fireEvent.click(screen.getByRole("button", { name: "Borrar la organización…" }));
    const dialogo = await screen.findByRole("dialog");
    fireEvent.change(within(dialogo).getByLabelText(/para confirmar/), { target: { value: "Acme Consultores" } });
    fireEvent.click(within(dialogo).getByRole("button", { name: "Borrar definitivamente" }));

    expect(await within(dialogo).findByRole("button", { name: "Volver a entrar" })).toBeInTheDocument();
    expect(useOrganizationStore.getState().activeOrganizationId).toBe(7);
  });
});
