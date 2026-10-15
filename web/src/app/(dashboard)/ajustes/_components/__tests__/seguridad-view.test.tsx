/**
 * Ajustes › Seguridad: activar y quitar la verificación en dos pasos (CU-25).
 *
 * El login ya pedía el código a quien lo tenía activo, pero no había pantalla
 * para activarlo: la página pública de seguridad prometía algo que solo se
 * podía hacer con curl. Lo que fija este suite es el recorrido entero contra
 * las cuatro llamadas de la API, y los dos fallos que tienen arreglo: el código
 * equivocado y la sesión antigua.
 */
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { sesion, refresh } = vi.hoisted(() => ({
  sesion: { mfa: false },
  refresh: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("@/lib/auth", () => ({
  useSession: () => ({
    user: { user_id: "1", email: "ana@example.com", display_name: null, is_admin: false, mfa_required: sesion.mfa },
    isLoading: false,
    isAuthenticated: true,
    isAdmin: false,
    refresh,
  }),
}));

import SeguridadView from "@/app/(dashboard)/ajustes/_components/seguridad-view";

const URI = "otpauth://totp/TenderFlow:ana%40example.com?secret=JBSWY3DPEHPK3PXP&issuer=TenderFlow";
const RECUPERACION = Array.from({ length: 10 }, (_, i) => `${i}`.repeat(16).slice(0, 16));

type Respuesta = { status: number; body: unknown };
let respuestas: Record<string, Respuesta>;
const fetchMock = vi.fn();

function responder(clave: string, status: number, body: unknown) {
  respuestas[clave] = { status, body };
}

function renderVista() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SeguridadView />
    </QueryClientProvider>,
  );
}

function llamada(metodo: string, ruta: string) {
  return fetchMock.mock.calls.find(
    ([url, init]) => String(url) === ruta && (init as RequestInit | undefined)?.method === metodo,
  );
}

beforeEach(() => {
  sesion.mfa = false;
  respuestas = {
    "POST /api/v1/auth/totp/setup": { status: 200, body: { otpauth_uri: URI } },
    "POST /api/v1/auth/totp/confirm": { status: 200, body: { status: "ok", recovery_codes: RECUPERACION } },
    "DELETE /api/v1/auth/totp": { status: 200, body: { status: "ok" } },
  };
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    const r = respuestas[`${init?.method ?? "GET"} ${url}`] ?? { status: 404, body: {} };
    return Promise.resolve(
      new Response(JSON.stringify(r.body), { status: r.status, headers: { "Content-Type": "application/json" } }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("Seguridad: alta", () => {
  it("sin el segundo factor, lo explica y ofrece activarlo", () => {
    renderVista();
    expect(screen.getByText(/no tiene la verificación en dos pasos/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Activar" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Desactivar/ })).not.toBeInTheDocument();
  });

  it("al empezar enseña la clave en bloques, y copiarla copia la clave sin espacios", async () => {
    renderVista();
    fireEvent.click(screen.getByRole("button", { name: "Activar" }));

    expect(await screen.findByText("JBSW Y3DP EHPK 3PXP")).toBeInTheDocument();
    expect(llamada("POST", "/api/v1/auth/totp/setup")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Copiar clave" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("JBSWY3DPEHPK3PXP"));
    // En el móvil, el enlace otpauth abre la app con la cuenta ya rellena.
    expect(screen.getByRole("link", { name: /Abrir en la app/ })).toHaveAttribute("href", URI);
  });

  it("confirmar con el código enseña los códigos de recuperación una vez", async () => {
    renderVista();
    fireEvent.click(screen.getByRole("button", { name: "Activar" }));
    const campo = await screen.findByLabelText(/Código de seis cifras/);

    const confirmar = screen.getByRole("button", { name: "Confirmar" });
    expect(confirmar).toBeDisabled();
    fireEvent.change(campo, { target: { value: "123 456" } });
    fireEvent.click(confirmar);

    const lista = await screen.findByRole("list", { name: "Códigos de recuperación" });
    expect(within(lista).getAllByRole("listitem")).toHaveLength(10);
    const [, init] = llamada("POST", "/api/v1/auth/totp/confirm")!;
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({ code: "123456" });
    expect(refresh).toHaveBeenCalled();

    // Ya guardados, desaparecen: no hay forma de volver a pedirlos.
    fireEvent.click(screen.getByRole("button", { name: "Ya los he guardado" }));
    expect(screen.queryByRole("list", { name: "Códigos de recuperación" })).not.toBeInTheDocument();
  });

  it("un código equivocado se dice en línea y deja seguir probando", async () => {
    responder("POST /api/v1/auth/totp/confirm", 400, { detail: "Invalid TOTP code" });
    renderVista();
    fireEvent.click(screen.getByRole("button", { name: "Activar" }));
    fireEvent.change(await screen.findByLabelText(/Código de seis cifras/), { target: { value: "000000" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));

    expect(await screen.findByText(/El código no es válido/)).toBeInTheDocument();
    expect(screen.getByText("JBSW Y3DP EHPK 3PXP")).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("cancelar vuelve al principio sin activar nada", async () => {
    renderVista();
    fireEvent.click(screen.getByRole("button", { name: "Activar" }));
    await screen.findByText("JBSW Y3DP EHPK 3PXP");
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByText("JBSW Y3DP EHPK 3PXP")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Activar" })).toBeInTheDocument();
  });

  it("con la sesión antigua ofrece volver a entrar en vez de decir «sin permiso»", async () => {
    responder("POST /api/v1/auth/totp/setup", 403, {
      type: "https://licitaciones-sap/errors/reauthentication-required",
      detail: "Reauthenticate before performing this sensitive operation.",
    });
    renderVista();
    fireEvent.click(screen.getByRole("button", { name: "Activar" }));

    expect(await screen.findByRole("button", { name: "Volver a entrar" })).toBeInTheDocument();
    expect(screen.queryByText(/permiso/)).not.toBeInTheDocument();
  });
});

describe("Seguridad: baja", () => {
  beforeEach(() => {
    sesion.mfa = true;
  });

  it("con el segundo factor activo lo dice y pide un código para quitarlo", async () => {
    renderVista();
    expect(screen.getByText(/está activa/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Activar" })).not.toBeInTheDocument();

    const desactivar = screen.getByRole("button", { name: "Desactivar" });
    expect(desactivar).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Código de la app o de recuperación/), {
      target: { value: "0123-4567-89ab-cdef" },
    });
    expect(desactivar).toBeEnabled();
    fireEvent.click(desactivar);

    await waitFor(() => expect(refresh).toHaveBeenCalled());
    const [, init] = llamada("DELETE", "/api/v1/auth/totp")!;
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({ code: "0123456789abcdef" });
  });

  it("un código que no vale no desactiva nada", async () => {
    responder("DELETE /api/v1/auth/totp", 400, { detail: "Invalid MFA code" });
    renderVista();
    fireEvent.change(screen.getByLabelText(/Código de la app o de recuperación/), { target: { value: "111111" } });
    fireEvent.click(screen.getByRole("button", { name: "Desactivar" }));

    expect(await screen.findByText(/El código no es válido/)).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });
});
