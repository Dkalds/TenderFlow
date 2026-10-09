import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionProvider } from "@/lib/auth";
import { TooltipProvider } from "@/components/ui/tooltip";
import { callMethod, callUrl, jsonResponse } from "@/hooks/__tests__/fetch-call";

/**
 * Usuarios de la instancia: quién es administrador y quién sigue teniendo acceso.
 *
 * «Hacer administrador» se ejecutaba al primer clic, sin confirmación, mientras
 * reencolar una entrada de la cola de errores sí la pedía. La columna «Estado»
 * decía siempre «Activo» porque la lista no traía a los desactivados, y la
 * baja no tenía botón aunque la API la ofrece desde hace meses.
 */

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/ops",
  useSearchParams: () => new URLSearchParams(),
}));

import { UsuariosCard } from "../_components/administracion/usuarios-card";

const USUARIOS = [
  { id: 1, email: "yo@tf.es", display_name: "Yo", is_admin: true, deactivated_at: null, last_access: null },
  { id: 2, email: "ana@tf.es", display_name: "Ana", is_admin: false, deactivated_at: null, last_access: null },
  {
    id: 3,
    email: "baja@tf.es",
    display_name: "Baja",
    is_admin: false,
    deactivated_at: "2026-09-01T10:00:00+00:00",
    last_access: null,
  },
];

function montar() {
  const fetchMock = vi.fn().mockImplementation((...call: unknown[]) => {
    const url = callUrl(call);
    if (url.startsWith("/api/v1/auth/me")) {
      return Promise.resolve(
        jsonResponse({ user_id: "1", email: "yo@tf.es", display_name: "Yo", is_admin: true }),
      );
    }
    if (callMethod(call) !== "GET") return Promise.resolve(jsonResponse({ status: "ok" }));
    return Promise.resolve(jsonResponse(USUARIOS));
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SessionProvider>
        <TooltipProvider>
          <UsuariosCard />
        </TooltipProvider>
      </SessionProvider>
    </QueryClientProvider>,
  );
  return fetchMock;
}

async function fila(email: string): Promise<HTMLElement> {
  const tr = (await screen.findByText(email)).closest("tr");
  if (!tr) throw new Error(`sin fila para ${email}`);
  return tr;
}

function escrituras(fetchMock: ReturnType<typeof vi.fn>) {
  return fetchMock.mock.calls.filter((c) => callMethod(c) !== "GET");
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("UsuariosCard", () => {
  it("pide también a los desactivados y los marca", async () => {
    const fetchMock = montar();

    expect(within(await fila("baja@tf.es")).getByText("Desactivado")).toBeInTheDocument();
    const lista = fetchMock.mock.calls.find((c) => callUrl(c).startsWith("/api/v1/admin/users"));
    expect(lista && callUrl(lista)).toContain("include_deactivated=true");
  });

  it("hacer administrador no se ejecuta al primer clic", async () => {
    const fetchMock = montar();
    const ana = await fila("ana@tf.es");

    fireEvent.click(within(ana).getByRole("button", { name: "Hacer administrador a ana@tf.es" }));
    expect(escrituras(fetchMock)).toHaveLength(0);

    fireEvent.click(
      within(ana).getByRole("button", { name: "Confirmar: hacer administrador a ana@tf.es" }),
    );
    await waitFor(() => expect(escrituras(fetchMock)).toHaveLength(1));
    const [put] = escrituras(fetchMock);
    expect(callMethod(put)).toBe("PUT");
    expect(callUrl(put)).toBe("/api/v1/admin/users/2/admin");
    expect(JSON.parse(String((put[1] as RequestInit).body))).toEqual({ is_admin: true });
  });

  it("cancelar deja la fila como estaba", async () => {
    const fetchMock = montar();
    const ana = await fila("ana@tf.es");

    fireEvent.click(within(ana).getByRole("button", { name: "Hacer administrador a ana@tf.es" }));
    fireEvent.click(within(ana).getByRole("button", { name: "Cancelar" }));

    expect(within(ana).getByRole("button", { name: "Hacer administrador a ana@tf.es" })).toBeInTheDocument();
    expect(escrituras(fetchMock)).toHaveLength(0);
  });

  it("tu propia fila no ofrece acciones que la API va a rechazar", async () => {
    montar();
    const yo = await fila("yo@tf.es");

    expect(within(yo).getByText("Tu cuenta")).toBeInTheDocument();
    expect(within(yo).queryByRole("button")).not.toBeInTheDocument();
  });

  it("desactiva tras confirmar, con la acción que espera la API", async () => {
    const fetchMock = montar();
    const ana = await fila("ana@tf.es");

    fireEvent.click(within(ana).getByRole("button", { name: "Desactivar a ana@tf.es" }));
    fireEvent.click(within(ana).getByRole("button", { name: "Confirmar: desactivar a ana@tf.es" }));

    await waitFor(() => expect(escrituras(fetchMock)).toHaveLength(1));
    const [post] = escrituras(fetchMock);
    expect(callUrl(post)).toBe("/api/v1/admin/users/2/deactivate");
    expect(JSON.parse(String((post[1] as RequestInit).body))).toEqual({ action: "deactivate" });
  });

  it("a quien está de baja le ofrece reactivar, no desactivar", async () => {
    const fetchMock = montar();
    const baja = await fila("baja@tf.es");

    expect(within(baja).queryByRole("button", { name: /Desactivar a/ })).not.toBeInTheDocument();
    fireEvent.click(within(baja).getByRole("button", { name: "Reactivar a baja@tf.es" }));
    fireEvent.click(within(baja).getByRole("button", { name: "Confirmar: reactivar a baja@tf.es" }));

    await waitFor(() => expect(escrituras(fetchMock)).toHaveLength(1));
    expect(JSON.parse(String((escrituras(fetchMock)[0][1] as RequestInit).body))).toEqual({
      action: "reactivate",
    });
  });
});
