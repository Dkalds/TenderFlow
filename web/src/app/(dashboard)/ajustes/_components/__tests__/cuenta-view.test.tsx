import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const session = { user: { email: "ana@example.test" }, isLoading: false };
vi.mock("@/lib/auth", () => ({ useSession: () => session }));

import CuentaView from "@/app/(dashboard)/ajustes/_components/cuenta-view";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/**
 * C7.5: `/mi-cuenta` la absorbió el espacio Ajustes como `?vista=cuenta`, así
 * que su `page.tsx` desapareció —un `page.tsx` bajo una ruta con 308 se compila
 * y no se ejecuta nunca, y el propio repo lo prohíbe (`titulos-de-pagina.test`)—.
 * Este test **no se borra**: cambia de sujeto al componente que ahora sí se
 * monta, y con él sigue cubriendo lo mismo.
 */
describe("Datos y cuenta", () => {
  it("ofrece el export de datos, que antes solo se alcanzaba con curl", () => {
    render(<CuentaView />);
    expect(screen.getByRole("button", { name: /Descargar mis datos/ })).toBeInTheDocument();
  });

  it("el borrado está bloqueado hasta escribir el email exacto", () => {
    // Es irreversible y anonimiza todo el histórico: un "¿estás seguro?" de un
    // clic no es confirmación suficiente.
    render(<CuentaView />);
    const boton = screen.getByRole("button", { name: /Eliminar mi cuenta definitivamente/ });
    expect(boton).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/para confirmar/), {
      target: { value: "otra@example.test" },
    });
    expect(boton).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/para confirmar/), {
      target: { value: "ana@example.test" },
    });
    expect(boton).toBeEnabled();
  });

  it("advierte de que el borrado no se puede deshacer", () => {
    render(<CuentaView />);
    expect(screen.getByText(/No se puede deshacer/)).toBeInTheDocument();
  });

  it("el borrado viaja con CSRF y con la confirmación que exige la API", async () => {
    // Regresión O0.7: el botón hacía `fetch("/api/v1/me", {method:"DELETE"})` a
    // pelo. `DELETE /me` cuelga de `require_recent_session` → `require_any_auth`,
    // que devuelve 403 «CSRF token mismatch» a toda mutación por cookie sin
    // `X-CSRF-Token`, y además exige cuerpo `{"confirmation":"DELETE"}`
    // (`DeleteMyDataRequest`). Sin las dos cosas el botón no borraba nada.
    document.cookie = "csrf_token=tok-123";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<CuentaView />);
    fireEvent.change(screen.getByLabelText(/para confirmar/), {
      target: { value: "ana@example.test" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Eliminar mi cuenta definitivamente/ }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/me");
    expect(init.method).toBe("DELETE");
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("tok-123");
    expect(JSON.parse(init.body as string)).toEqual({ confirmation: "DELETE" });
  });

  it("no pide confirmación de borrado si no hay sesión con email", () => {
    const original = session.user;
    // @ts-expect-error — se fuerza el caso de sesión sin email.
    session.user = null;
    render(<CuentaView />);
    expect(
      screen.queryByRole("button", { name: /Eliminar mi cuenta definitivamente/ }),
    ).not.toBeInTheDocument();
    session.user = original;
  });
});
