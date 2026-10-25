/**
 * Ops › Administración › Claves de API de la instancia (CU-20).
 *
 * La tarjeta que había aquí listaba las claves del propio administrador con el
 * rótulo «de la instancia». Lo que fija este suite: que se pide la ruta de
 * administración (no `/me/keys`), que una clave sin dueño o sin caducidad se
 * ve como tal, que el recuento es el del servidor aunque la lista llegue
 * recortada, y que revocar pide confirmación antes de llamar a la API.
 *
 * Los datos van tipados con el esquema generado: si el backend renombra un
 * campo, el test deja de compilar en vez de seguir pasando con una forma vieja.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ClaveInstancia, ClavesInstancia } from "@/app/(dashboard)/ops/_hooks/use-admin-api-keys";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { ClavesInstanciaCard } from "@/app/(dashboard)/ops/_components/administracion/claves-instancia-card";

const DE_ANA: ClaveInstancia = {
  id: 10,
  name: "Integración CRM",
  prefix: "abcdefgh",
  tier: "free",
  scopes: "data:read",
  user_id: 5,
  owner_email: "ana@empresa.es",
  owner_name: "Ana",
  owner_deactivated: false,
  organization_id: null,
  created_at: "2026-10-01T10:00:00+00:00",
  expires_at: "2026-12-30T10:00:00+00:00",
  last_used: "2026-10-20T08:00:00+00:00",
  estado: "activa",
};

const LEGADA: ClaveInstancia = {
  id: 3,
  name: "Script antiguo",
  prefix: null,
  tier: "free",
  scopes: "*",
  user_id: null,
  owner_email: null,
  owner_name: null,
  owner_deactivated: false,
  organization_id: null,
  created_at: "2026-05-01T10:00:00+00:00",
  expires_at: null,
  last_used: null,
  estado: "activa",
};

const REVOCADA: ClaveInstancia = { ...DE_ANA, id: 11, name: "Vieja de Ana", estado: "revocada" };

function respuesta(over: Partial<ClavesInstancia> = {}): ClavesInstancia {
  return {
    items: [DE_ANA, LEGADA, REVOCADA],
    resumen: { total: 3, activas: 2, activas_sin_dueno: 1, activas_sin_caducidad: 1 },
    truncado: false,
    ...over,
  };
}

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

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ClavesInstanciaCard />
    </QueryClientProvider>,
  );
}

async function fila(nombre: string) {
  const elemento = (await screen.findByText(nombre)).closest("tr");
  if (!elemento) throw new Error(`sin fila para ${nombre}`);
  return elemento;
}

beforeEach(() => {
  respuestas = {
    "GET /api/v1/admin/api-keys": { status: 200, body: respuesta() },
    "DELETE /api/v1/admin/api-keys/3": {
      status: 200,
      body: { id: 3, name: "Script antiguo", user_id: null, estado: "revocada" },
    },
  };
  fetchMock.mockImplementation((entrada: unknown, init?: RequestInit) => {
    const clave = `${metodoDe(entrada, init)} ${urlDe(entrada).split("?")[0]}`;
    const r = respuestas[clave] ?? { status: 404, body: { detail: "no está en el doble" } };
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

describe("Claves de la instancia: listado", () => {
  it("lee la ruta de administración y no las claves propias", async () => {
    renderCard();
    await fila("Integración CRM");
    expect(llamadas("GET", "/api/v1/admin/api-keys")).toHaveLength(1);
    expect(llamadas("GET", "/api/v1/me/keys")).toHaveLength(0);
  });

  it("marca la clave sin dueño y sin caducidad, y deja ver de quién es la otra", async () => {
    renderCard();
    const legada = await fila("Script antiguo");
    expect(within(legada).getByText("Sin dueño")).toBeTruthy();
    expect(within(legada).getByText("Nunca")).toBeTruthy();
    expect(within(legada).getByText("Sin uso registrado")).toBeTruthy();
    expect(within(legada).getByText("todos (*)")).toBeTruthy();

    const deAna = await fila("Integración CRM");
    expect(within(deAna).getByText("ana@empresa.es")).toBeTruthy();
    expect(within(deAna).queryByText("Sin dueño")).toBeNull();
  });

  it("pinta el recuento del servidor, no el de las filas", async () => {
    respuestas["GET /api/v1/admin/api-keys"] = {
      status: 200,
      body: respuesta({
        items: [LEGADA],
        resumen: { total: 101, activas: 89, activas_sin_dueno: 89, activas_sin_caducidad: 89 },
        truncado: true,
      }),
    };
    renderCard();
    await fila("Script antiguo");
    expect(screen.getAllByText("89")).toHaveLength(3);
    expect(screen.getByText("101")).toBeTruthy();
    expect(screen.getByText(/Parcial: se enseñan 1 de 101 claves/)).toBeTruthy();
  });

  it("dice que no hay claves cuando la instancia no tiene ninguna", async () => {
    respuestas["GET /api/v1/admin/api-keys"] = {
      status: 200,
      body: respuesta({
        items: [],
        resumen: { total: 0, activas: 0, activas_sin_dueno: 0, activas_sin_caducidad: 0 },
      }),
    };
    renderCard();
    expect(await screen.findByText("No hay ninguna clave de API en la instancia")).toBeTruthy();
  });

  it("enseña el error con opción de reintentar", async () => {
    respuestas["GET /api/v1/admin/api-keys"] = { status: 500, body: { detail: "fallo" } };
    renderCard();
    expect(await screen.findByText("No se pudieron cargar las claves")).toBeTruthy();
  });
});

describe("Claves de la instancia: revocar", () => {
  it("pide confirmación y solo entonces llama a la API", async () => {
    renderCard();
    const legada = await fila("Script antiguo");

    fireEvent.click(within(legada).getByRole("button", { name: "Revocar la clave Script antiguo" }));
    expect(llamadas("DELETE", "/api/v1/admin/api-keys")).toHaveLength(0);

    fireEvent.click(within(legada).getByRole("button", { name: "Confirmar: revocar la clave Script antiguo" }));
    await waitFor(() => expect(llamadas("DELETE", "/api/v1/admin/api-keys/3")).toHaveLength(1));
    // Tras revocar se vuelve a pedir la lista: la fila cambia de estado con el dato real.
    await waitFor(() => expect(llamadas("GET", "/api/v1/admin/api-keys").length).toBeGreaterThan(1));
  });

  it("cancelar no revoca nada", async () => {
    renderCard();
    const legada = await fila("Script antiguo");
    fireEvent.click(within(legada).getByRole("button", { name: "Revocar la clave Script antiguo" }));
    fireEvent.click(within(legada).getByRole("button", { name: "Cancelar" }));
    expect(within(legada).getByRole("button", { name: "Revocar la clave Script antiguo" })).toBeTruthy();
    expect(llamadas("DELETE", "/api/v1/admin/api-keys")).toHaveLength(0);
  });

  it("no ofrece revocar una clave ya revocada", async () => {
    renderCard();
    const revocada = await fila("Vieja de Ana");
    expect(within(revocada).queryByRole("button", { name: /Revocar/ })).toBeNull();
    expect(within(revocada).getByText("Revocada")).toBeTruthy();
  });
});
