/**
 * Ajustes › Claves: crear, rotar y revocar (CU-14).
 *
 * La pantalla creaba y listaba, y nada más: `POST /me/keys/rotate` no tenía
 * consumidor, revocar una clave concreta no existía, y Ops › Administración
 * afirmaba que cada persona «crea, rota y revoca las suyas». Lo que fija este
 * suite es que la clave nueva se enseña una sola vez (también al rotar), que
 * revocar pide confirmación, y que la sesión antigua ofrece volver a entrar.
 */
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import ClavesView from "@/app/(dashboard)/ajustes/_components/claves-view";

const REAUTENTICACION = {
  type: "https://licitaciones-sap/errors/reauthentication-required",
  detail: "Reauthenticate before performing this sensitive operation.",
};

const ACTIVA = {
  id: 7,
  name: "CRM",
  tier: "standard",
  is_active: true,
  created_at: "2026-09-01T10:00:00+00:00",
  expires_at: "2099-01-01T00:00:00+00:00",
  last_used: "2026-10-10T08:00:00+00:00",
};
const REVOCADA = { ...ACTIVA, id: 8, name: "Vieja", is_active: false, last_used: null };

type Respuesta = { status: number; body: unknown };
let respuestas: Record<string, Respuesta>;
const fetchMock = vi.fn();

function urlDe(entrada: unknown): string {
  const cruda = entrada instanceof Request ? entrada.url : String(entrada);
  return cruda.replace(/^https?:\/\/[^/]+/, "");
}

function metodoDe(entrada: unknown, init?: RequestInit): string {
  return entrada instanceof Request ? entrada.method : (init?.method ?? "GET");
}

function llamadas(metodo: string, prefijo: string) {
  return fetchMock.mock.calls.filter(
    ([entrada, init]) => metodoDe(entrada, init as RequestInit) === metodo && urlDe(entrada).startsWith(prefijo),
  );
}

function renderVista() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ClavesView />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  respuestas = {
    "GET /api/v1/me/keys": { status: 200, body: { items: [ACTIVA, REVOCADA] } },
    "DELETE /api/v1/me/keys/7": { status: 204, body: null },
    "POST /api/v1/me/keys/rotate": {
      status: 201,
      body: { new_token: "tf_nueva", message: "", old_key_expires_at: "2026-10-19T10:00:00+00:00" },
    },
    "POST /api/v1/me/keys": { status: 201, body: { id: 9, name: "ERP", api_key: "tf_creada" } },
  };
  fetchMock.mockImplementation((entrada: unknown, init?: RequestInit) => {
    const clave = `${metodoDe(entrada, init)} ${urlDe(entrada).split("?")[0]}`;
    const r = respuestas[clave] ?? { status: 404, body: {} };
    return Promise.resolve(
      r.status === 204
        ? new Response(null, { status: 204 })
        : new Response(JSON.stringify(r.body), { status: r.status, headers: { "Content-Type": "application/json" } }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

async function fila(nombre: string) {
  const elemento = (await screen.findByText(nombre)).closest("li");
  if (!elemento) throw new Error(`sin fila para ${nombre}`);
  return elemento;
}

describe("Claves: listado", () => {
  it("dice el estado y el último uso de cada clave, y solo ofrece acciones a las vivas", async () => {
    renderVista();
    const activa = await fila("CRM");
    expect(within(activa).getByText(/Último uso/)).toBeInTheDocument();
    expect(within(activa).getByRole("button", { name: "Rotar" })).toBeInTheDocument();
    expect(within(activa).getByRole("button", { name: "Revocar" })).toBeInTheDocument();

    const revocada = await fila("Vieja");
    expect(within(revocada).getByText("Revocada")).toBeInTheDocument();
    expect(within(revocada).getByText(/Sin usar/)).toBeInTheDocument();
    expect(within(revocada).queryByRole("button")).not.toBeInTheDocument();
  });

  it("una clave caducada no se puede rotar: la API ya no la acepta", async () => {
    respuestas["GET /api/v1/me/keys"] = {
      status: 200,
      body: { items: [{ ...ACTIVA, expires_at: "2020-01-01T00:00:00+00:00" }] },
    };
    renderVista();
    const caducada = await fila("CRM");
    expect(within(caducada).getByText("Caducada")).toBeInTheDocument();
    expect(within(caducada).queryByRole("button", { name: "Rotar" })).not.toBeInTheDocument();
  });
});

describe("Claves: revocar", () => {
  it("pide confirmación y apaga la clave", async () => {
    renderVista();
    fireEvent.click(within(await fila("CRM")).getByRole("button", { name: "Revocar" }));

    const dialogo = await screen.findByRole("dialog");
    expect(within(dialogo).getByText(/dejará de entrar al momento/)).toBeInTheDocument();
    fireEvent.click(within(dialogo).getByRole("button", { name: "Revocar clave" }));

    await waitFor(() => expect(llamadas("DELETE", "/api/v1/me/keys/7")).toHaveLength(1));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // El listado se vuelve a pedir: la fila tiene que decir que ya no vale.
    await waitFor(() => expect(llamadas("GET", "/api/v1/me/keys").length).toBeGreaterThan(1));
  });

  it("con la sesión antigua ofrece volver a entrar dentro del diálogo", async () => {
    respuestas["DELETE /api/v1/me/keys/7"] = { status: 403, body: REAUTENTICACION };
    renderVista();
    fireEvent.click(within(await fila("CRM")).getByRole("button", { name: "Revocar" }));
    const dialogo = await screen.findByRole("dialog");
    fireEvent.click(within(dialogo).getByRole("button", { name: "Revocar clave" }));

    expect(await within(dialogo).findByRole("button", { name: "Volver a entrar" })).toBeInTheDocument();
  });
});

describe("Claves: rotar", () => {
  it("entrega la clave nueva una sola vez y dice hasta cuándo vale la anterior", async () => {
    renderVista();
    fireEvent.click(within(await fila("CRM")).getByRole("button", { name: "Rotar" }));

    const dialogo = await screen.findByRole("dialog");
    // Una semana de gracia por defecto, como la API.
    expect(within(dialogo).getByRole("button", { name: "Una semana" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(within(dialogo).getByRole("button", { name: "Un día" }));
    fireEvent.click(within(dialogo).getByRole("button", { name: "Rotar clave" }));

    const aviso = await screen.findByRole("alert");
    expect(within(aviso).getByText("tf_nueva")).toBeInTheDocument();
    expect(within(aviso).getByText(/La anterior sigue valiendo hasta/)).toBeInTheDocument();
    const [peticion] = llamadas("POST", "/api/v1/me/keys/rotate");
    expect(urlDe(peticion[0])).toBe("/api/v1/me/keys/rotate?key_id=7&grace_days=1");

    fireEvent.click(within(aviso).getByRole("button", { name: "Ya la he guardado" }));
    expect(screen.queryByText("tf_nueva")).not.toBeInTheDocument();
  });

  it("sin gracia, dice que la anterior ya no vale", async () => {
    respuestas["POST /api/v1/me/keys/rotate"] = {
      status: 201,
      body: { new_token: "tf_nueva", message: "", old_key_expires_at: "2026-10-12T10:00:00+00:00" },
    };
    renderVista();
    fireEvent.click(within(await fila("CRM")).getByRole("button", { name: "Rotar" }));
    const dialogo = await screen.findByRole("dialog");
    fireEvent.click(within(dialogo).getByRole("button", { name: "Ninguno" }));
    fireEvent.click(within(dialogo).getByRole("button", { name: "Rotar clave" }));

    expect(await screen.findByText(/La anterior ya no vale/)).toBeInTheDocument();
  });
});

describe("Claves: crear", () => {
  it("con la sesión antigua ofrece volver a entrar en vez de un aviso mudo", async () => {
    respuestas["POST /api/v1/me/keys"] = { status: 403, body: REAUTENTICACION };
    renderVista();
    fireEvent.change(await screen.findByLabelText("Nombre"), { target: { value: "ERP" } });
    fireEvent.click(screen.getByRole("button", { name: "Crear" }));

    expect(await screen.findByRole("button", { name: "Volver a entrar" })).toBeInTheDocument();
  });
});
