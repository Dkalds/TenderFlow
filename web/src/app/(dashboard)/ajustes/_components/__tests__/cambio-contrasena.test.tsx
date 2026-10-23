/**
 * Ajustes › Seguridad: cambiar la contraseña con la actual (CU-19).
 *
 * Lo que fija: el cuerpo que viaja (sin la confirmación, que es del
 * formulario), la política de la nueva antes de enviar, y que la respuesta de
 * la API —«la contraseña actual no es correcta»— se lee junto al formulario.
 */
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { toast } = vi.hoisted(() => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("sonner", () => ({ toast }));

import { CambioContrasena } from "@/app/(dashboard)/ajustes/_components/cambio-contrasena";

const RUTA = "/api/v1/auth/password/change";
const ACTUAL = "Actual-2026-Segura";
const NUEVA = "Nueva-2026-Segura";

let respuesta: { status: number; body: unknown };
const fetchMock = vi.fn();

function renderVista() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CambioContrasena />
    </QueryClientProvider>,
  );
}

function escribir(etiqueta: string, valor: string) {
  fireEvent.change(screen.getByLabelText(etiqueta), { target: { value: valor } });
}

function rellenar(actual: string, nueva: string, confirmacion = nueva) {
  escribir("Contraseña actual", actual);
  escribir("Contraseña nueva", nueva);
  escribir("Repite la contraseña nueva", confirmacion);
  fireEvent.click(screen.getByRole("button", { name: "Cambiar contraseña" }));
}

function llamadas() {
  return fetchMock.mock.calls.filter(([url]) => String(url) === RUTA);
}

beforeEach(() => {
  respuesta = { status: 200, body: { status: "ok" } };
  fetchMock.mockImplementation(() =>
    Promise.resolve(
      new Response(JSON.stringify(respuesta.body), {
        status: respuesta.status,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("CambioContrasena", () => {
  it("avisa de lo que pasa fuera de esta pantalla antes de enviar", () => {
    renderVista();

    expect(screen.getByText(/se cierran las demás y tus claves de API dejan de valer/)).toBeInTheDocument();
  });

  it("envía la actual y la nueva, sin la confirmación, y vacía el formulario", async () => {
    renderVista();

    rellenar(ACTUAL, NUEVA);

    await waitFor(() => expect(llamadas()).toHaveLength(1));
    const init = llamadas()[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ current_password: ACTUAL, new_password: NUEVA });
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Contraseña cambiada"));
    await waitFor(() => expect(screen.getByLabelText("Contraseña actual")).toHaveValue(""));
  });

  it("no envía si la confirmación no coincide", async () => {
    renderVista();

    rellenar(ACTUAL, NUEVA, "Otra-2026-Segura");

    expect(await screen.findByText("Las contraseñas no coinciden.")).toBeInTheDocument();
    expect(llamadas()).toHaveLength(0);
  });

  it("aplica la política del alta a la nueva antes de enviar", async () => {
    renderVista();

    rellenar(ACTUAL, "sinmayusculas2026");

    expect(await screen.findByText("Tiene que llevar alguna mayúscula.")).toBeInTheDocument();
    expect(screen.getByLabelText("Contraseña nueva")).toHaveAttribute("aria-invalid", "true");
    expect(llamadas()).toHaveLength(0);
  });

  it("enseña junto al formulario por qué la API lo rechazó", async () => {
    respuesta = { status: 400, body: { detail: "La contraseña actual no es correcta." } };
    renderVista();

    rellenar("Equivocada-2026", NUEVA);

    expect(await screen.findByText("La contraseña actual no es correcta.")).toBeInTheDocument();
    expect(toast.success).not.toHaveBeenCalled();
    // Lo escrito sigue ahí: corregir la actual no obliga a repetir la nueva.
    expect(screen.getByLabelText("Contraseña nueva")).toHaveValue(NUEVA);
  });
});
